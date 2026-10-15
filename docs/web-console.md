# Console web et overlay en direct

Les deux fichiers Compose incluent désormais un service `web` utilisant la même
image que le relais. Publiez/reconstruisez cette image avant de redéployer.
L’interface est en français et accessible sur le port interne **8080** du service
`web`. Elle fonctionne avec les configurations RTMP et RTMPS.

## Un même domaine pour la console et la réception du flux

Le domaine **`ingest.monolithoid.com`** peut servir à la console web et à la
réception vidéo sur le même VPS. Les services se distinguent par leurs ports :

| Usage | Adresse publique | Destination |
| --- | --- | --- |
| Console et connexion Google | `https://ingest.monolithoid.com` (TCP 443) | Proxy HTTPS Coolify → `web:8080` |
| Réception RTMP, Compose standard | `rtmp://ingest.monolithoid.com:1935` | Port TCP 1935 de MediaMTX |
| Réception RTMPS, Compose alternatif | `rtmps://ingest.monolithoid.com:1936` | Port TCP 1936 de MediaMTX |

Les ports sont ceux par défaut. Choisir **un seul** des deux fichiers Compose,
RTMP ou RTMPS ; ils ne se fusionnent pas. Dans Streamcaster, utiliser `live` avec le compte de publication pour RTMP,
ou la valeur secrète de `INGEST_STREAM_KEY` comme clé de flux pour RTMPS,
comme indiqué dans le [guide RTMPS](rtmps.md) ou le README pour RTMP.

### DNS et pare-feu

- Créer ou vérifier l’enregistrement DNS `A` de `ingest.monolithoid.com` vers
  l’IPv4 publique du VPS. Ne publier un `AAAA` que si l’IPv6 du VPS et son
  routage vers ces services fonctionnent également.
- Si le DNS est géré par Cloudflare, sélectionner **DNS uniquement** (nuage gris)
  pour ce nom partagé : le proxy Cloudflare standard ne transporte pas RTMP/RTMPS.
  Le site HTTPS reste chiffré grâce au certificat du proxy Coolify sur le VPS.
- Autoriser TCP **443** pour la console, ainsi que TCP **1935** pour RTMP ou
  **1936** pour RTMPS, dans les pare-feu du fournisseur et du VPS. Si Coolify
  utilise la validation ACME HTTP-01 ou la redirection HTTP vers HTTPS, autoriser
  également TCP **80** vers son proxy.
- Garder le port **8080** interne à Docker : `web` le déclare avec `expose`,
  sans publication sur le VPS. Aucun port hôte n’est réservé pour la console.
  Le port RTSP **8554** reste interne au réseau Docker.

### Routage HTTPS dans Coolify et certificats

Associer le domaine public `https://ingest.monolithoid.com` au service **`web`**,
avec **8080 comme port cible interne**. Si la version de Coolify demande le port
cible dans le champ Domains, saisir `https://ingest.monolithoid.com:8080` ; ce
suffixe sert au routage interne. L’adresse publique et `WEB_PUBLIC_URL` restent
`https://ingest.monolithoid.com`, sans `:8080`.

Le proxy Coolify doit partager un réseau Docker avec `web` pour joindre
`web:8080`. Ne pas router les ports RTMP/RTMPS dans le proxy HTTP et laisser
Domains vide pour `mediamtx` et `relay`.

Le certificat HTTPS de la console est géré par Coolify sur le port 443.
Pour RTMPS, MediaMTX doit aussi disposer d’un certificat valide pour
`ingest.monolithoid.com`, monté dans `/certs` depuis `RTMPS_CERTS_DIR`.
Le certificat de Coolify n’est pas automatiquement partagé avec MediaMTX.
Suivre la procédure [Certbot OVH et renouvellement RTMPS](rtmps.md) ; son défi
DNS-01 peut fonctionner pendant que Coolify occupe les ports 80/443.

La connexion Google protège la console et ses API. L’authentification de la
publication vidéo reste celle du Compose choisi ; la variante RTMPS du dépôt
exige la clé de flux secrète `INGEST_STREAM_KEY`, sans identifiant/mot de passe
côté Streamcaster. Le chemin `live` et les clés incorrectes y sont refusés.

### Erreur « Bind for 0.0.0.0:8080 failed: port is already allocated »

Cette erreur signifie qu’un déploiement tente de publier le port 8080 sur le VPS,
alors qu’un autre conteneur ou processus l’utilise déjà. Le port interne 8080 peut
être utilisé par plusieurs conteneurs ; le conflit porte sur sa publication hôte.

Pour la console derrière Coolify, conserver uniquement cette déclaration dans
le service `web`, dans le fichier Compose sélectionné :

```yaml
expose:
  - "8080"
```

Supprimer le bloc `ports` de `web` et tout mapping de port hôte ajouté dans
Coolify, puis redéployer. Le proxy doit continuer à cibler `web:8080`.
`WEB_PUBLIC_URL=https://ingest.monolithoid.com` et l’URI de redirection Google
ne changent pas. Les anciennes variables `WEB_PORT` et `WEB_BIND_IP` ne sont
plus utilisées. Il n’est pas nécessaire d’arrêter le service qui occupe déjà
le port 8080 du VPS.

Si un proxy installé directement sur l’hôte doit joindre la console, ajouter
explicitement un mapping de boucle locale dans une surcharge Compose locale :

```yaml
services:
  web:
    ports:
      - "127.0.0.1:18080:8080"
```

Choisir un port hôte libre (ici 18080) et faire pointer ce proxy vers
`127.0.0.1:18080`. Le port interne et les paramètres OAuth restent inchangés.
Cette surcharge est inutile pour le proxy Docker de Coolify.

## Connexion Google et HTTPS

1. Créer un client OAuth **Application Web** dans Google Cloud / Google Auth Platform.
   Configurer l’écran de consentement et les utilisateurs de test si l’application
   est en mode test. Aucun accès à YouTube ou Drive n’est demandé : seuls
   `openid email profile` sont utilisés.
2. Ajouter l’URI de redirection exacte :
   `https://ingest.monolithoid.com/auth/callback`.
3. Dans `.env` ou les variables Coolify, définir :

   ```dotenv
   WEB_PUBLIC_URL=https://ingest.monolithoid.com
   WEB_SECRET_KEY=<résultat de openssl rand -hex 32>
   GOOGLE_CLIENT_ID=<client OAuth Google>
   GOOGLE_CLIENT_SECRET=<secret OAuth Google>
   GOOGLE_ALLOWED_EMAILS=operateur@gmail.com,autre@exemple.fr
   ```

4. Faire pointer un domaine **HTTPS** vers `web:8080` via le reverse proxy de
   Coolify. Le proxy doit partager le réseau Docker du service. Aucun mapping
   de port hôte n’est nécessaire. Garder les secrets dans les variables
   protégées, jamais dans Git.
5. Redéployer puis ouvrir `https://ingest.monolithoid.com` et choisir
   « Continuer avec Google ».

Dans Google Auth Platform, renseigner également `monolithoid.com` comme domaine
autorisé si l’écran de consentement le demande (vérifier sa propriété si Google
l’exige). Si une origine JavaScript autorisée est demandée, utiliser
`https://ingest.monolithoid.com` ; ce flux OAuth côté serveur repose sur l’URI
de redirection exacte `https://ingest.monolithoid.com/auth/callback`, sans port
8080. `WEB_PUBLIC_URL` ne doit pas contenir de chemin ni `/auth/callback`.

Sans configuration complète ou sans liste de comptes, l’accès reste fermé
(page de connexion HTTP 503). Le relais peut fonctionner même si Google n’est
pas encore configuré. Seules les adresses explicitement autorisées et vérifiées
par Google accèdent à la console et aux API. Les sessions expirent après huit
heures d’inactivité ; cookies HTTPS/HttpOnly/SameSite et jeton CSRF protègent les modifications.
Les endpoints statiques et `/healthz` sont publics, sans données de diffusion.
Le serveur doit pouvoir joindre `accounts.google.com`, `oauth2.googleapis.com`
et `www.googleapis.com` en HTTPS pour les échanges OpenID Connect.

## Vérifier la mise en service du domaine

1. Vérifier que le DNS de `ingest.monolithoid.com` résout vers le VPS et que
   `https://ingest.monolithoid.com/login` présente un certificat valide.
2. Se connecter avec un compte présent dans `GOOGLE_ALLOWED_EMAILS` et, si
   l’application Google est en test, dans sa liste d’utilisateurs de test.
3. Vérifier qu’un autre compte ne peut pas accéder à la console. Sans session,
   `/api/status` et `/api/overlay.png` doivent répondre HTTP 401.
4. Publier le flux vers le même nom sur le port 1935 ou 1936 selon le Compose,
   puis vérifier le statut de la console et le résultat dans YouTube Studio.
5. Modifier une zone, valider et vérifier son apparition dans la sortie vidéo.

En cas de `redirect_uri_mismatch`, comparer l’URI enregistrée dans Google Cloud
à `https://ingest.monolithoid.com/auth/callback` et vérifier `WEB_PUBLIC_URL`.
Une erreur HTTP 502 côté console indique de vérifier le port cible 8080, le
réseau partagé avec le proxy et la santé du service `web`. Une page de connexion
HTTP 503 indique une configuration OAuth, une clé de session, une URL publique
ou une liste de comptes manquante/invalide.

## Paramètres à copier dans Streamcaster

L’encart « Envoyer la vidéo vers la régie » affiche les paramètres de réception
avec des boutons **Copier**. La clé et le mot de passe sont masqués par défaut
et peuvent être révélés avec **Afficher**. L’encart est réservé aux comptes
Google autorisés, comme le reste de la console.

- Compose RTMPS : serveur `rtmps://ingest.monolithoid.com:1936`, clé issue de
  `INGEST_STREAM_KEY` et authentification désactivée dans Streamcaster.
- Compose RTMP : serveur `rtmp://ingest.monolithoid.com:1935`, clé `live`,
  identifiant et mot de passe issus de `PUBLISH_USER` et `PUBLISH_PASSWORD`.

Les deux Compose transmettent automatiquement ces paramètres au service `web`.
L’hôte est repris de `WEB_PUBLIC_URL` ; le protocole et le port viennent du Compose
sélectionné et de `RTMP_PORT` ou `RTMPS_PORT`. Si le serveur de réception utilise
un autre nom public, définir `INGEST_PUBLIC_URL`, par exemple
`rtmps://video.example.com:1936`, sans identifiants ni clé dans l’URL.
Cette variable sert à l’affichage et ne modifie pas la configuration MediaMTX.

La clé YouTube et le mot de passe de lecture interne du relais ne sont pas
transmis à cet encart. Après mise à jour, recréer `web` pour qu’il reçoive les
nouvelles variables du Compose. Vérifier la copie des valeurs sans les publier
dans les logs ou captures d’écran.

## Préparer et diffuser un overlay

- Ajouter des zones ou choisir « Créer un tableau de score ».
- Saisir les scores, équipes et informations de l’événement.
- Ajuster X, Y, largeur, hauteur, taille du texte et couleurs.
- Les couleurs utilisent `#RRGGBBAA` : `00` pour un alpha transparent,
  `FF` pour opaque. Le texte est coupé aux limites de sa zone.
- Le champ « Nom de la zone » sert uniquement à repérer la zone dans l’éditeur ;
  modifier « Texte affiché » pour changer le contenu visible.
- L’aperçu est généré par le serveur avec le même rendu que l’image publiée.
  Le damier indique la transparence et ne figure pas dans le PNG.
- Cliquer sur **Valider et diffuser** pour écrire atomiquement le PNG RGBA.
  FFmpeg relit l’image à une cadence de 1 Hz, sans redémarrer l’encodeur.
  Prévoir quelques secondes de prise en compte, en plus du délai YouTube.
- « Télécharger le PNG diffusé » récupère la dernière version validée.

L’image d’origine `OVERLAY_IMAGE` (par défaut `/assets/overlay.png`) sert de base
au rendu, en haut à gauche sans redimensionnement (les parties hors cadre sont coupées). Pour un overlay entièrement vide en dehors des textes, fournir une
image RGBA transparente. Les zones s’ajoutent par-dessus cette base. Pour changer
la base ou les dimensions : adapter les variables/le fichier, puis redémarrer
`web` et valider à nouveau les zones (en les adaptant au nouveau format).

Les brouillons restent dans la page jusqu’à validation. Les zones validées et le
PNG sont persistés dans le volume `overlay-data`, partagé en lecture seule avec
le relais. Ne pas supprimer ce volume lors d’une mise à jour. Les modifications
concurrentes sont détectées : une console qui utilise une ancienne révision doit
recharger la page avant de pouvoir publier. Une seule instance Gunicorn à quatre
threads est configurée pour sérialiser les écritures ; ne pas augmenter le nombre
de workers ou répliquer le service sans ajouter un verrou interprocessus.

## Informations du flux

Le relais écrit toutes les deux secondes un état JSON dans `relay-status`, lu
uniquement par la console. L’interface interroge cette donnée toutes les trois
secondes : caméra ou image d’attente, progression de l’encodeur, format et débit
vidéo **configuré**. Un état vieux de dix secondes est affiché comme indisponible.
Aucune URL de diffusion, clé YouTube ou mot de passe n’est inclus dans ce statut.
Les paramètres de publication affichés dans l’encart de connexion proviennent
d’une API privée distincte.

« Encodage actif » indique que FFmpeg progresse ; ce statut ne certifie pas que
YouTube a rendu la vidéo publique. Il n’y a pas de lecteur vidéo dans la console.

## Si l’overlay semble ne pas changer

L’éditeur affiche « Éditeur prêt » après son chargement. À chaque modification,
le message devient « Aperçu actualisé » une fois le nouveau PNG reçu. Les erreurs
HTTP, de session et de script sont affichées sous l’aperçu. Les URL du script et
de la feuille de style portent une version calculée à partir de leur contenu.
Si le message reste sur « Chargement de l’éditeur », vérifier dans le navigateur
que JavaScript et `/static/app.js` sont accessibles et qu’aucune politique CSP
ajoutée par le proxy ne bloque le script, les requêtes API ou les images `blob:`.

Après validation, la console compare l’empreinte du PNG enregistré à celle du
fichier que le relais voit à `/data/overlay/overlay.png`. La confirmation indique
que le fichier est disponible au relais ; elle ne mesure pas son apparition sur
YouTube, qui ajoute son propre délai vidéo.

- Si le relais ne confirme pas le PNG : vérifier le volume partagé `overlay-data`
  et le chemin `OVERLAY_IMAGE` résolu dans le service `relay`.
- Si la confirmation n’est pas fournie : vérifier que `web` **et** `relay` ont été
  recréés avec la même nouvelle image Docker. Modifier seulement le Compose ne
  remplace pas une ancienne image en cours d’exécution.
- Si le PNG téléchargé change mais pas la vidéo malgré la confirmation : conserver
  les logs de `relay`, vérifier l’image réellement exécutée et tenir compte du
  délai de la plateforme de diffusion.
- Si rien ne se passe dans l’éditeur : relever le message sous l’aperçu et les
  erreurs de la console du navigateur, puis vérifier les réponses aux requêtes
  `/api/preview` et `/api/overlay` dans l’onglet Réseau.

## Vérifications locales

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check web/static/app.js
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example -f docker-compose.rtmps.yml config --quiet
```

FFmpeg et la police DejaVu Sans Bold sont nécessaires aux tests du rendu et du
rechargement. Le test de l’encodeur enregistre réellement un FLV, remplace le PNG
pendant l’encodage puis vérifie les couleurs et la transparence des images décodées.
Les tests Google simulent le retour OAuth ; une connexion Google réelle nécessite
le client OAuth et le domaine HTTPS du déploiement.
