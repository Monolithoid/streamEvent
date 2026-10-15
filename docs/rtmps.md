# Streamcaster → MediaMTX en RTMPS

Le fichier `docker-compose.rtmps.yml` est une alternative autonome au Compose
RTMP. Il publie uniquement RTMPS sur TCP 1936 par défaut, avec publication anonyme
sur le chemin `live`. La lecture RTSP du relais reste privée et authentifiée.
Le relais et sa sortie YouTube sont identiques à ceux du Compose RTMP.

TLS chiffre la connexion et permet au téléphone de vérifier le serveur. Le compte
`any` autorise toute personne qui atteint ce port à publier sur `live` ; TLS
n'authentifie pas l'émetteur. `overridePublisher: no` reste activé.

## Certificat sur le VPS

Le nom `ingest.monolithoid.com` doit pointer directement vers le VPS, sans proxy
HTTP/CDN. Un certificat publiquement reconnu doit couvrir exactement ce nom.
Utiliser un client ACME, par exemple Certbot, avec renouvellement automatisé.
Le défi DNS-01 permet l'émission sans modifier le proxy web Coolify ; HTTP-01
nécessite un routage explicite du défi sur le port 80.

Pour un premier certificat avec validation DNS manuelle sur Debian/Ubuntu :

```sh
sudo apt-get update
sudo apt-get install -y certbot
sudo certbot certonly --manual --preferred-challenges dns -d ingest.monolithoid.com
```

Créer le TXT `_acme-challenge.ingest.monolithoid.com` avec la valeur affichée,
attendre sa propagation puis valider dans Certbot. Après émission, les sources
à copier ci-dessous sont
`/etc/letsencrypt/live/ingest.monolithoid.com/fullchain.pem` et
`/etc/letsencrypt/live/ingest.monolithoid.com/privkey.pem`.
Cette méthode manuelle ne permet pas le renouvellement automatique : pour une
exploitation durable, utiliser le plugin DNS de son fournisseur et un hook de
copie/redémarrage. Ne pas supposer que `certbot renew` automatisera un défi manuel.

Le certificat HTTPS géré par le proxy Coolify n'est pas automatiquement fourni à
MediaMTX. La rubrique Domains de MediaMTX doit rester vide. Ne pas remplacer le
certificat par un certificat d'origine réservé à un CDN ou un certificat autosigné
si le téléphone ne lui fait pas explicitement confiance.

Préparer sur le serveur Docker cible un dossier, par exemple
`/opt/basket-live/certs`, avec :

- `fullchain.pem` : certificat du domaine et intermédiaires ;
- `privkey.pem` : clé privée correspondante, jamais dans Git ni dans le chat.

Pour copier des fichiers existants, adapter les deux sources réelles :

```sh
sudo install -d -m 0700 /opt/basket-live/certs
sudo install -m 0644 /CHEMIN_SOURCE/fullchain.pem /opt/basket-live/certs/fullchain.pem
sudo install -m 0600 /CHEMIN_SOURCE/privkey.pem /opt/basket-live/certs/privkey.pem
```

MediaMTX utilise l'utilisateur par défaut de son image ; ne pas rendre la clé
publique pour contourner un problème de droits. Les copies doivent être de vrais
fichiers : les liens symboliques Certbot `live/` pointent généralement hors du
dossier et ne fonctionnent pas dans ce montage isolé.

Le hook de renouvellement ACME doit recopier les deux fichiers puis redémarrer
uniquement le conteneur MediaMTX. Un renouvellement du certificat du proxy Coolify
ne met pas ces copies à jour. Le redémarrage coupe brièvement l'entrée ; le relais
reste lancé et peut afficher l'attente pendant la reconnexion du téléphone.

## Déploiement Coolify

1. Mettre les nouveaux fichiers du dépôt à disposition de Coolify.
2. Choisir `/docker-compose.rtmps.yml` comme Docker Compose Location. Ce fichier
   est autonome : ne pas le fusionner avec `/docker-compose.yml`, ce qui pourrait
   conserver une publication de port RTMP.
3. Conserver `MEDIAMTX_CONFIG` vers le fichier persistant du VPS, qui doit garder
   `authMethod: internal` et `authInternalUsers: []`, puis les variables du relais, notamment `RELAY_IMAGE`, `READ_USER`,
   `READ_PASSWORD`, `YOUTUBE_STREAM_KEY` et les paramètres des images/vidéo.
4. Ajouter `RTMPS_CERTS_DIR=/opt/basket-live/certs`. Facultativement, définir
   `RTMPS_BIND_IP=0.0.0.0` et `RTMPS_PORT=1936`.
5. Supprimer l'ancienne variable JSON `MTX_AUTHINTERNALUSERS` et toute variable
   numérotée d'authentification définie séparément qui contredirait le Compose.
   `PUBLISH_USER` et `PUBLISH_PASSWORD` ne sont pas utilisés par cette variante.
6. Autoriser TCP 1936 sur le pare-feu du fournisseur et du VPS. Le port 443 peut
   rester occupé par le proxy HTTPS Coolify. Fermer l'ancienne règle RTMP 1935
   lorsqu'elle n'est plus utilisée par un autre service.
7. Enregistrer et redéployer. La recréation du relais peut couper la sortie YouTube.

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
Clé : live
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
