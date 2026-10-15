# Basket Live Stream

Relais sans interface graphique pour diffuser du basket 3×3 :

**Téléphone → MediaMTX → FFmpeg réception → commutation Python → FFmpeg sortie → YouTube RTMPS.**

Sans téléphone, la sortie continue avec une image d’attente et du silence. Les
basculements conservent l’encodeur de sortie et sa connexion. Une panne du réseau
sortant ou un redémarrage exige en revanche une nouvelle connexion ; la conservation
du même événement YouTube doit être vérifiée sur YouTube.

## Images à télécharger

Le Compose de production utilise uniquement `image:`, aucun `build:` :

| Service | Image | Provenance |
| --- | --- | --- |
| Réception | `bluenviron/mediamtx:1.15.3` | Image officielle du projet MediaMTX |
| Relais | `monolithoid/streamevent-relay:<version>` | Image de ce projet contenant Python, FFmpeg et le contrôleur |

Le relais est construit **dans GitHub Actions**, pas sur le VPS. Sa base est
l’image officielle Python ; FFmpeg vient des dépôts Debian avec leurs correctifs
de sécurité. Aucun GPU, OBS, serveur graphique ni paquet Python tiers n’est requis.
Les bibliothèques multimédias du paquet Debian FFmpeg sont incluses dans l’image.

**L’image du relais doit d’abord être publiée.** La présence de ce dépôt ne signifie
pas qu’une image Docker Hub est déjà disponible.

1. Créer ou choisir le dépôt **`monolithoid/streamevent-relay`** dans Docker Hub.
   Créer un jeton d’accès Docker Hub avec les droits de lecture/écriture sur ce
   dépôt. Ne pas utiliser le mot de passe du compte dans le workflow.
2. Dans GitHub → Settings → Secrets and variables → Actions, ajouter :
   - secret `DOCKERHUB_USERNAME` : `monolithoid` ;
   - secret `DOCKERHUB_TOKEN` : le jeton Docker Hub. Le saisir directement dans
     GitHub, jamais dans Git, Coolify ou un message de chat.
   La variable de dépôt `DOCKERHUB_IMAGE` est facultative : elle permet de remplacer
   la destination par défaut `monolithoid/streamevent-relay`, sans tag ni registre.
3. Pousser/fusionner sur `main` et autoriser GitHub Actions.
   Le workflow `Test and publish relay` construit et teste le conteneur, puis publie
   les tags `main` et `sha-<SHA complet>`. Un tag Git `v…` publie le même tag d’image.
   Une destination invalide bloque explicitement la publication.
4. Rendre le dépôt Docker Hub public pour permettre le téléchargement anonyme.
   Pour un dépôt privé, configurer dans Coolify un accès à `docker.io` avec un
   compte/jeton de lecture. Avec Compose local, utiliser `docker login` si nécessaire.
5. Définir `RELAY_IMAGE` avec le tag SHA, une version, ou idéalement le digest indiqué
   par Actions. `main` est un raccourci mutable pour les premiers essais.

Pour un fork ou un autre dépôt Docker Hub, renseigner `DOCKERHUB_IMAGE` et adapter
`RELAY_IMAGE` au même `compte/depot`, par exemple `compte/depot:main`.
Les pull requests construisent/testent sans publier. Cible initiale : Linux amd64.

## Installation Docker Compose

Prérequis : Linux, Docker Engine, Compose v2 et Git. Python/FFmpeg sur l’hôte ne
sont nécessaires que pour les tests de développement.

```sh
git clone https://github.com/Monolithoid/streamEvent.git
cd streamEvent
cp .env.example .env
chmod 600 .env
openssl rand -hex 24
openssl rand -hex 24
```

Reporter les deux mots de passe différents dans `.env`, remplacer la clé YouTube
et choisir l’image Docker Hub publiée. Pour les utilisateurs/mots de passe MediaMTX,
utiliser uniquement lettres, chiffres, tirets et underscores : ils sont transmis
par les variables du Compose. Ne pas utiliser `any` comme utilisateur.

```sh
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f --tail=100 relay mediamtx
```

`config --quiet` valide sans afficher les secrets résolus. Ne jamais commiter `.env`,
une clé YouTube ou des captures de configuration. L’attente est émise dès le démarrage.

## Déploiement Coolify depuis Git

Le [guide Coolify et stockage VPS](docs/coolify.md) détaille tous les champs de
déploiement, les variables à renseigner, les montages persistants et les contrôles
à effectuer avant un match.

1. Publier l’image Docker Hub comme décrit ci-dessus.
2. Créer une ressource depuis le dépôt Git, choisir **Docker Compose** avec
   `/docker-compose.yml`. Ne pas sélectionner Dockerfile/Nixpacks.
3. Renseigner les variables de `.env.example`, particulièrement `RELAY_IMAGE`, les
   deux comptes MediaMTX et les paramètres YouTube. Les secrets sont stockés dans Coolify.
4. Copier `config/mediamtx.yml` dans `/opt/basket-live/config/mediamtx.yml` sur le
   VPS et définir `MEDIAMTX_CONFIG` avec ce chemin absolu dans Coolify. Ce chemin
   persistant est aussi la valeur par défaut du Compose. Pour conserver les images
   indépendamment des redéploiements, les placer sur le VPS, par exemple
   `/opt/basket-live/assets`, et définir `ASSETS_DIR=/opt/basket-live/assets`.
   Dossier et fichiers doivent déjà exister et
   être traversables/lisibles par l’UID 10001, par exemple permissions `755`/`644`.
5. Dans les volumes Coolify, vérifier que `/mediamtx.yml` pointe vers le fichier
   persistant du VPS et `/assets` vers le bon dossier. Le montage MediaMTX refuse
   un chemin absent au lieu de créer un dossier vide.
6. Ouvrir `1935/TCP` dans le pare-feu OVH et celui du VPS, puis déployer.
7. Vérifier les logs et la prévisualisation YouTube Studio.

Aucun domaine HTTP, proxy web Coolify ou certificat web n’est nécessaire. Le port
RTMP doit être libre ; `RTMP_PORT` permet de le changer. Aucun réseau host, socket
Docker ou privilège étendu. Les limites initiales sont 5 CPU/1,5 Go pour le relais
et 1 CPU/512 Mo pour MediaMTX ; ajuster après mesure avec les autres services.

`MEDIAMTX_CONFIG` désigne un fichier sur le serveur Docker, pas un chemin dans le
conteneur ni un nom de volume Docker. En local, `.env.example` utilise le fichier
Git `./config/mediamtx.yml`. Les comptes restent configurés par
les variables numérotées `MTX_AUTHINTERNALUSERS_*`.

## YouTube et gestion des sessions

Activer YouTube Live à l’avance : l’activation initiale peut être différée. Créer
un événement et choisir sa clé réutilisable dans YouTube Studio.

```dotenv
YOUTUBE_RTMPS_URL=rtmps://a.rtmps.youtube.com:443/live2
YOUTUBE_STREAM_KEY=votre-cle-secrete
```

Utiliser l’URL RTMPS fournie par YouTube si elle diffère. **Désactiver l’arrêt
automatique** dans Studio. Le relais transmet dès son démarrage ; vérifier la
prévisualisation puis cliquer sur « Passer au direct » si le démarrage manuel est actif.

Entre deux matchs, arrêter uniquement la publication du téléphone : l’attente
continue. Pour terminer toute la session, arrêter le relais puis terminer
explicitement l’événement dans Studio :

```sh
docker compose stop relay
# Reprendre ; YouTube peut demander un nouvel événement.
docker compose start relay
# Arrêter les deux services sans supprimer les fichiers montés.
docker compose down
```

Dans Coolify, utiliser les commandes de la ressource. Redéployer le relais ou
changer sa configuration coupe la connexion RTMPS.

## Téléphone Android

Utiliser une application permettant la publication RTMP personnalisée, par exemple
Larix Broadcaster (vérifier les fonctions et conditions de la version installée).
Configurer une connexion RTMP :

```text
rtmp://ADRESSE_DU_VPS:1935/live?user=phone&pass=VOTRE_MOT_DE_PASSE
```

Remplacer `phone` par `PUBLISH_USER`. Si l’application sépare serveur et clé :
serveur `rtmp://ADRESSE_DU_VPS:1935`, clé `live?user=phone&pass=VOTRE_MOT_DE_PASSE`.
Les champs d’authentification propres à l’application peuvent différer ; cette URL
utilise le mécanisme MediaMTX vérifié par le test synthétique.

Choisir H.264, AAC, paysage, 1080p30 à environ 6 Mbit/s si le réseau montant le
permet, sinon 720p30 à 3–4 Mbit/s. Désactiver l’économie de batterie de l’application
et tester sur le terrain. RTMP ne chiffre ni les identifiants ni la vidéo. Ne
jamais utiliser la clé YouTube ou un mot de passe réutilisé ailleurs sur le téléphone.

## Entrée RTMPS pour Streamcaster

La variante autonome [`docker-compose.rtmps.yml`](docker-compose.rtmps.yml)
permet de publier sans identifiants sur `live`, avec chiffrement TLS et lecture
interne du relais authentifiée. Elle exige un certificat valide monté depuis le
VPS ; le certificat HTTPS du proxy Coolify n'est pas automatiquement disponible.
Voir le [guide RTMPS, certificats et renouvellement](docs/rtmps.md).

## Images et paramètres

Les PNG fournis sont des exemples neutres. Remplacer `waiting.png` par une image
1920×1080 et `overlay.png` par un PNG RGBA transparent. L’overlay est posé en haut
à gauche sans redimensionnement, sur le match et sur l’attente. Un calque de la
taille de sortie permet de positionner logo et équipes. Préparer un calque adapté
à 720p si nécessaire ; éviter qu’il dépasse la taille de sortie.

L’attente et la vidéo sont redimensionnées en conservant les proportions.
Redémarrer le relais après remplacement : l’attente est préchargée et l’overlay
est ouvert au démarrage de l’encodeur.

```dotenv
WIDTH=1280
HEIGHT=720
FPS=30
VIDEO_BITRATE=3500k
ENCODER_PRESET=veryfast
ENCODER_THREADS=4
WAITING_IMAGE=/assets/waiting.png
OVERLAY_IMAGE=/assets/overlay.png
```

FPS acceptés : 25, 30, 50, 60 ; démarrer à 30. Sortie H.264/YUV420p, GOP de deux
secondes, débit vidéo cible constant. AAC toujours présent, stéréo 48 kHz/128 kbit/s,
y compris lorsque le téléphone n’a pas de piste audio.

## Réseau et SRT ultérieur

| Direction | Port | Usage |
| --- | --- | --- |
| Public entrant | TCP 1935 par défaut | Téléphone RTMP |
| Docker privé | TCP 8554 | Lecture RTSP du relais |
| Sortant | TCP 443 | RTMPS YouTube et images HTTPS |
| Sortant | DNS selon l’hôte | Résolution des noms |

API, métriques, HLS, WebRTC et SRT sont désactivés. RTSP utilise TCP uniquement,
sans port RTP/UDP. Les ports Docker peuvent contourner certaines règles UFW :
vérifier le filtrage OVH et la chaîne DOCKER-USER.

SRT reste une évolution de configuration à valider : activer `srt: yes`, publier
`8890:8890/udp`, configurer le `streamid` MediaMTX
`publish:live:utilisateur:motdepasse` dans le téléphone. Pour chiffrer, définir
`srtPublishPassphrase` sur le chemin et la même passphrase dans l’application.
Vérifier les paramètres avec la version épinglée avant ouverture du port.
La lecture RTSP interne et le relais restent identiques.

## Tests sans YouTube

Prérequis de test : Docker Compose, Python ≥3.10, FFmpeg/ffprobe avec libx264 sur
l’hôte. Le projet de test est indépendant et utilise uniquement les ports loopback
19350 et 18554, avec des identifiants factices. Ne pas lancer deux tests simultanés.

```sh
python3 -m unittest discover -s tests -v
docker compose --env-file .env.example config --quiet
python3 tests/integration.py
# Tester exactement le conteneur publié, son FFmpeg et son UID non root :
python3 tests/integration.py --image monolithoid/streamevent-relay:VOTRE_TAG
```

Les logs et `continuous.flv` restent dans `test-results/`, ignoré par Git. Le test
vérifie les basculements, les timestamps, les pixels, le son/silence et la reprise
après panne du récepteur. Il nettoie ses conteneurs en fin d’exécution.
Voir [la procédure complète](docs/validation.md).

Source synthétique manuelle pour tester le VPS :

```sh
ffmpeg -re -f lavfi -i 'testsrc2=size=1280x720:rate=30' \
  -re -f lavfi -i 'sine=frequency=880:sample_rate=48000' \
  -c:v libx264 -preset veryfast -tune zerolatency -g 60 \
  -c:a aac -f flv \
  'rtmp://ADRESSE_DU_VPS:1935/live?user=phone&pass=MOT_DE_PASSE'
```

Ctrl-C simule le départ du téléphone. Sans audio : enlever l’entrée `sine` et
remplacer `-c:a aac` par `-an`. Ne pas partager l’historique contenant le mot de passe.

## Logs, santé et ressources

```sh
docker compose logs --tail=100 -f relay
docker compose logs --tail=100 -f mediamtx
docker stats --no-stream
docker compose top relay
```

Dans Coolify : Logs et Metrics, ou les mêmes commandes depuis le dossier de
déploiement. `switch state=live/waiting` indique un basculement ; `output_started`
doit rester unique pendant les transitions normales. `output_lost` indique une
rupture sortante ; `decoder_stalled` une réception bloquée ; `scheduler_overrun`
une incapacité à tenir la cadence. Réduire la résolution/charge dans ce dernier cas.
Rotation des logs : trois fichiers de 10 Mo par service.

Le healthcheck vérifie l’avancement de l’encodage. Docker Compose ne redémarre pas
un conteneur simplement « unhealthy » : le contrôleur gère lui-même ses processus.
`unless-stopped` reprend un processus principal mort, pas un événement YouTube clôturé.

Les logs du relais masquent les URL et secrets connus. Les variables Docker et
arguments FFmpeg restent accessibles aux administrateurs de l’hôte : protéger
l’accès VPS/Coolify et ne pas publier un dump d’inspection.

## Limites

Une panne du VPS, du réseau sortant ou de YouTube exige une reconnexion, avec un
délai progressif de 1 à 30 secondes. YouTube décide de conserver ou non l’événement.
La stabilité en conditions réelles, la charge 1080p et la synchronisation labiale
doivent être mesurées avant un match public.

La sélection de la dernière image et le tampon audio d’une demi-seconde privilégient
une mémoire/latence bornées. Ils ne garantissent pas une synchronisation labiale
précise pour tous les téléphones. Un changement de pistes audio en cours de flux
demande une reconnexion. Une image figée dont les paquets continuent n’est pas
détectée comme une panne.

Voir [l’architecture](docs/architecture.md). Licence MIT.

Les [résultats locaux](docs/test-report.md) détaillent ce qui a été vérifié et les
limites des sources synthétiques.
