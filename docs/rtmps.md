# Streamcaster → MediaMTX en RTMPS

Le fichier `docker-compose.rtmps.yml` est une alternative autonome au Compose
RTMP. Il publie uniquement RTMPS sur TCP 1936 par défaut, avec une clé secrète
`INGEST_STREAM_KEY` comme chemin de publication. La lecture RTSP du relais
utilise le même chemin et reste privée et authentifiée.
Le relais et sa sortie YouTube sont identiques à ceux du Compose RTMP.

TLS chiffre la connexion et permet au téléphone de vérifier le serveur. Le compte
`any` autorise la publication uniquement sur le chemin exact défini par cette clé ;
`live` et les autres clés sont refusés. La connaissance de la clé donne accès à
la publication, comme une clé de stream YouTube. TLS seul n'authentifie pas
l'émetteur. `overridePublisher: no` reste activé.

Générer une clé avec `openssl rand -hex 32`, puis enregistrer sa valeur dans
`INGEST_STREAM_KEY` dans Coolify (ou dans le fichier `.env`). Utiliser uniquement
les 64 caractères hexadécimaux générés, sans `/`, `?` ou préfixe `~`. Garder une
clé distincte de `YOUTUBE_STREAM_KEY` pour pouvoir les renouveler séparément.
Ne pas enregistrer la vraie clé dans Git. Les logs MediaMTX peuvent contenir le
chemin : les traiter comme confidentiels. Pour changer la clé, modifier la variable,
redéployer les deux services et mettre à jour Streamcaster.

## Let’s Encrypt automatique avec OVH

Le nom `ingest.monolithoid.com` doit pointer directement vers le VPS, sans proxy
HTTP/CDN. Le plugin Certbot OVH crée et supprime automatiquement les TXT du défi
DNS-01. Aucun port HTTP supplémentaire ni arrêt du proxy Coolify n'est nécessaire.
Le certificat HTTPS du proxy Coolify n'est pas automatiquement fourni à MediaMTX ;
laisser la rubrique Domains du service MediaMTX vide.

Le même nom peut aussi servir la console sur `https://ingest.monolithoid.com`
(port 443), tandis que Streamcaster publie sur `rtmps://ingest.monolithoid.com:1936`.
Associer le domaine HTTPS au service `web` et au port cible 8080 dans Coolify.
Configurer `WEB_PUBLIC_URL=https://ingest.monolithoid.com` et l’URI Google
`https://ingest.monolithoid.com/auth/callback` selon le
[guide complet DNS, proxy et connexion Google](web-console.md). Les certificats
HTTPS de Coolify et RTMPS de MediaMTX restent gérés séparément.

Ces commandes s'exécutent sur le **VPS Docker cible**, sous Debian/Ubuntu. Utiliser
une seule installation de Certbot : si Certbot est déjà installé par Snap ou une
autre méthode, installer le plugin OVH correspondant plutôt que mélanger les
installations. Pour une installation par les paquets Debian/Ubuntu :

```sh
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-dns-ovh openssl
```

### Accès DNS OVH

Créer des identifiants API dans le [portail OVH Europe](https://eu.api.ovh.com/createToken/),
avec des droits limités à la zone `monolithoid.com` :

| Méthode | Chemin |
| --- | --- |
| GET | `/domain/zone/` |
| GET | `/domain/zone/monolithoid.com` |
| GET | `/domain/zone/monolithoid.com/*` |
| POST | `/domain/zone/monolithoid.com/record` |
| POST | `/domain/zone/monolithoid.com/refresh` |
| DELETE | `/domain/zone/monolithoid.com/record/*` |

Les autorisations doivent rester valides pour les renouvellements futurs ;
prévoir leur rotation avant expiration si une durée limitée est choisie.
Conserver les trois valeurs uniquement sur le VPS, jamais dans Git, Coolify ou
le chat. Créer le fichier protégé puis l'éditer directement :

```sh
sudo install -d -m 0700 /root/.secrets/certbot
sudo touch /root/.secrets/certbot/ovh.ini
sudo chmod 0600 /root/.secrets/certbot/ovh.ini
sudoedit /root/.secrets/certbot/ovh.ini
```

Contenu à remplir avec les valeurs OVH :

```ini
dns_ovh_endpoint = ovh-eu
dns_ovh_application_key = VOTRE_APPLICATION_KEY
dns_ovh_application_secret = VOTRE_APPLICATION_SECRET
dns_ovh_consumer_key = VOTRE_CONSUMER_KEY
```

### Émission, copie et renouvellement

Depuis une copie du dépôt sur le VPS, installer le hook fourni avant l'émission :

```sh
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 0755 scripts/deploy_rtmps_certificate.sh \
  /etc/letsencrypt/renewal-hooks/deploy/streamevent-rtmps

sudo certbot certonly --dns-ovh \
  --dns-ovh-credentials /root/.secrets/certbot/ovh.ini \
  --dns-ovh-propagation-seconds 120 \
  --cert-name ingest.monolithoid.com \
  -d ingest.monolithoid.com
```

Certbot utilise Let’s Encrypt. Le certificat public et la clé privée sont stockés
sous `/etc/letsencrypt/live/ingest.monolithoid.com/`. Le hook copie automatiquement
les vrais fichiers `fullchain.pem` et `privkey.pem` dans `/opt/basket-live/certs`
(dossier `0700`, clé `0600`), après vérification du nom et de la correspondance
certificat/clé. Cela évite de monter des liens symboliques dont les cibles restent
hors du conteneur. MediaMTX utilise l'utilisateur par défaut de son image.

À chaque renouvellement réussi, le hook recopie les fichiers et redémarre les
conteneurs MediaMTX qui montent ce dossier précis. Le relais reste lancé ; l'entrée
est brièvement interrompue et le téléphone doit se reconnecter. Le hook ignore
les certificats des autres domaines. Pour un autre domaine ou dossier, adapter
les valeurs par défaut du hook avant son installation et le Compose en conséquence.

Activer le renouvellement périodique et tester le défi DNS avec les paquets apt :

```sh
sudo systemctl enable --now certbot.timer
sudo certbot renew --cert-name ingest.monolithoid.com --dry-run
```

Le test `--dry-run` vérifie le renouvellement sans lancer le hook de déploiement.
Pour tester aussi la copie et le redémarrage, hors direct :

```sh
sudo certbot renew --cert-name ingest.monolithoid.com --dry-run --run-deploy-hooks
```

Certbot exécute alors le hook avec le certificat actif, pas le certificat de test.
Si un certificat a déjà été émis avec `--manual`, migrer explicitement sa méthode
de renouvellement vers `dns-ovh` avant de considérer l'automatisation opérationnelle
(`certbot reconfigure` sur les versions qui le proposent). Un certificat manuel
existant ne devient pas automatiquement renouvelable par l'installation du plugin.

## Déploiement Coolify

1. Mettre les nouveaux fichiers du dépôt à disposition de Coolify.
2. Choisir `/docker-compose.rtmps.yml` comme Docker Compose Location. Ce fichier
   est autonome : ne pas le fusionner avec `/docker-compose.yml`, ce qui pourrait
   conserver une publication de port RTMP.
3. Conserver `MEDIAMTX_CONFIG` vers le fichier persistant du VPS, qui doit garder
   `authMethod: internal` et `authInternalUsers: []`, puis les variables du relais, notamment `RELAY_IMAGE`, `READ_USER`,
   `READ_PASSWORD`, `YOUTUBE_STREAM_KEY` et les paramètres des images/vidéo.
4. Ajouter `INGEST_STREAM_KEY` avec la clé générée ci-dessus (obligatoire, sans
   valeur par défaut `live`) et `RTMPS_CERTS_DIR=/opt/basket-live/certs`. Facultativement, définir
   `RTMPS_BIND_IP=0.0.0.0` et `RTMPS_PORT=1936`.
5. Supprimer l'ancienne variable JSON `MTX_AUTHINTERNALUSERS` et toute variable
   numérotée d'authentification définie séparément qui contredirait le Compose.
   `PUBLISH_USER` et `PUBLISH_PASSWORD` ne sont pas utilisés par cette variante.
6. Autoriser TCP 1936 sur le pare-feu du fournisseur et du VPS. Le port 443 peut
   rester occupé par le proxy HTTPS Coolify. Fermer l'ancienne règle RTMP 1935
   lorsqu'elle n'est plus utilisée par un autre service.
7. Enregistrer et redéployer. La recréation du relais peut couper la sortie YouTube.

Le chemin par défaut des certificats est `/opt/basket-live/certs`, surchargeable
par `RTMPS_CERTS_DIR`. La source utilise `${RTMPS_CERTS_DIR:-/opt/basket-live/certs}` :
le validateur de volumes Coolify accepte cette valeur par défaut, mais pas la
syntaxe Compose `${RTMPS_CERTS_DIR:?message}`.
Le montage échoue explicitement si le dossier des certificats n'existe pas.
Dans les logs MediaMTX, vérifier l'ouverture du listener RTMPS sur `:1936` et
l'absence d'erreur de chargement du certificat/de la clé.

Pour Compose en ligne de commande :

```sh
docker compose --env-file .env -f docker-compose.rtmps.yml config --quiet
docker compose --env-file .env -f docker-compose.rtmps.yml up -d
```

## Streamcaster et vérification

```text
Serveur : rtmps://ingest.monolithoid.com:1936
Clé : valeur de INGEST_STREAM_KEY
Authentification : désactivée
```

L'application doit prendre en charge une destination RTMPS personnalisée.
Vérifier d'abord TLS depuis un poste extérieur, avec OpenSSL :

```sh
openssl s_client -connect ingest.monolithoid.com:1936 \
  -servername ingest.monolithoid.com \
  -verify_hostname ingest.monolithoid.com -verify_return_error </dev/null
```

Une connexion réussie avec `Verify return code: 0 (ok)` valide la chaîne et le nom
selon les autorités de confiance du poste de test. Elle ne valide pas la publication
RTMP : lancer ensuite Streamcaster et vérifier le passage à `live` dans les logs
du relais et l'image dans YouTube Studio. Garder `logLevel: info` en exploitation.
Vérifier aussi qu'une publication avec la clé `live` ou une clé erronée est refusée.
