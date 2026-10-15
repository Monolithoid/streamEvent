# Déploiement Coolify et stockage persistant sur le VPS

Ce guide correspond au `docker-compose.yml` de production du dépôt : deux services,
`mediamtx` et `relay`, sans compilation sur le VPS. Les noms des rubriques Coolify
peuvent varier selon la version installée. Les chemins « hôte » désignent le VPS
Docker cible, y compris si Coolify est installé sur un autre serveur.

## 1. Préparer le déploiement

- Disposer d'un VPS Linux amd64 avec Docker et d'un serveur cible opérationnel dans
  Coolify. La publication actuelle de l'image du relais cible Linux amd64.
- Publier l'image `monolithoid/streamevent-relay` suivant la procédure du
  [README](../README.md#images-à-télécharger). Choisir son tag de version, son tag
  `sha-<SHA complet>` ou son digest pour retrouver exactement la même livraison.
- Prévoir les ressources des deux services en plus de Coolify et des autres
  applications : quotas initiaux de 5 CPU et 1 536 Mio pour `relay`, 1 CPU et
  512 Mio pour `mediamtx`. Ce sont des limites, pas une mesure de la capacité
  nécessaire ; valider la charge sur le VPS, notamment en 1080p.
- Activer YouTube Live et créer un événement dans YouTube Studio. Récupérer son
  URL RTMPS et sa clé de diffusion. Désactiver l'arrêt automatique de l'événement
  pour permettre les phases d'attente.
- Préparer les fichiers persistants décrits en section 4 avant le premier lancement.

## 2. Champs de la ressource Coolify

Créer une application depuis Git dans le projet et l'environnement souhaités.

| Champ / rubrique | Valeur à renseigner |
| --- | --- |
| Serveur / destination | Le VPS et la destination Docker qui exécuteront les deux services. |
| Dépôt Git | `https://github.com/Monolithoid/streamEvent` ou votre fork ; autoriser l'accès Git si le dépôt est privé. |
| Branche | `main`, ou la branche contenant le Compose à déployer. |
| Build Pack / type | **Docker Compose**. |
| Base Directory | `/` : racine du dépôt. |
| Docker Compose Location | `/docker-compose.yml`. |
| Domaines | Laisser vide pour les deux services ; la réception utilise directement le port RTMP du VPS. |
| Proxy HTTP / port HTTP | Aucun routage HTTP à configurer. Ne pas associer le port RTMP à un domaine HTTP du proxy. |
| Commandes de build / démarrage | Conserver le comportement Compose ; les images contiennent déjà leurs commandes. |
| Variables d'environnement | Renseigner les valeurs de la section 3 avant de déployer. |
| Stockage / Persistent Storage | Vérifier les bind mounts de la section 4 ; ne pas ajouter un second montage sur la même destination. |
| Healthcheck | Conserver celui du Compose pour `relay` ; aucun endpoint HTTP à saisir. |
| Déploiement automatique | Au choix ; chaque redéploiement du relais coupe la connexion YouTube. Pour les matchs, préférer un déploiement manuel hors direct. |

Le dépôt Git et l'image du relais sont deux sources distinctes : une mise à jour
de Git ne construit pas l'image dans Coolify. Mettre à jour `RELAY_IMAGE` pour
déployer une nouvelle version du relais. Si son dépôt Docker Hub est privé,
configurer l'authentification au registre `docker.io` dans Coolify avec un jeton
de lecture. Les secrets GitHub Actions `DOCKERHUB_USERNAME` et `DOCKERHUB_TOKEN`
servent à publier l'image et ne sont pas des variables applicatives à recopier.

Conserver le réseau privé `stream`, les limites, la rotation des logs et la
politique `restart: unless-stopped` du Compose. Le relais dispose déjà de son
healthcheck Docker ; l'état `unhealthy` seul ne provoque pas un redémarrage par
Docker Compose.

## 3. Variables à saisir dans Coolify

Dans **Environment Variables**, saisir les valeurs sans guillemets englobants.
Elles doivent être disponibles à l'interpolation du Compose de production lors
du déploiement. Si Coolify distingue les environnements de prévisualisation,
ne pas leur donner la clé YouTube de production : une prévisualisation peut
émettre un flux dès son lancement. Aucun argument de construction d'image
n'est requis.

Les valeurs ci-dessous sont celles du Compose et de `.env.example`, sauf
`ASSETS_DIR` qui propose ici un chemin persistant absolu sur le VPS. Remplacer
tous les exemples de secrets. Pour les deux comptes MediaMTX, utiliser uniquement
lettres, chiffres, tirets et underscores : leurs valeurs sont interpolées dans
du JSON. Ne pas utiliser `any` comme nom d'utilisateur.

### Image, authentification et YouTube

| Variable | Valeur / exemple | Rôle |
| --- | --- | --- |
| `RELAY_IMAGE` | `monolithoid/streamevent-relay:main` pour un premier essai ; préférer ensuite une version, un tag SHA ou `monolithoid/streamevent-relay@sha256:<digest publié>` | Obligatoire, image déjà publiée du relais. |
| `PUBLISH_USER` | `phone` | Obligatoire, compte de publication utilisé par le téléphone. |
| `PUBLISH_PASSWORD` | Un premier secret généré avec `openssl rand -hex 24` | Obligatoire, mot de passe du téléphone. |
| `READ_USER` | `relay` | Compte de lecture interne ; valeur par défaut si omise. |
| `READ_PASSWORD` | Un second secret généré avec `openssl rand -hex 24` | Obligatoire, différent du mot de passe de publication ; le téléphone n'en a pas besoin. |
| `YOUTUBE_RTMPS_URL` | `rtmps://a.rtmps.youtube.com:443/live2` | URL serveur fournie par Studio, sans la clé ; le relais exige RTMPS. |
| `YOUTUBE_STREAM_KEY` | La clé de l'événement YouTube | Obligatoire, clé seule, sans URL ni `/` ajouté devant. |

Marquer les mots de passe et la clé YouTube comme secrets dans Coolify lorsque
l'interface le permet. Ne pas les inscrire dans Git, les PNG, ni la configuration
MediaMTX. Les administrateurs Docker/Coolify peuvent accéder à la configuration
d'exécution : limiter ces accès. Aucun fichier `.env` manuel n'est nécessaire sur
le VPS pour un déploiement piloté par les variables Coolify.

### Réseau, vidéo et ressources

| Variable | Valeur initiale | Rôle / valeurs acceptées |
| --- | --- | --- |
| `RTMP_BIND_IP` | `0.0.0.0` | Écoute sur les interfaces du VPS. `127.0.0.1` empêche une connexion directe depuis le téléphone. Une IP précise doit appartenir au VPS. |
| `RTMP_PORT` | `1935` | Port TCP publié sur le VPS ; doit être libre. Le port du conteneur reste `1935`. |
| `WIDTH` | `1920` | Largeur de sortie, paire, de 16 à 3840. |
| `HEIGHT` | `1080` | Hauteur de sortie, paire, de 16 à 2160. |
| `FPS` | `30` | `25`, `30`, `50` ou `60`. Commencer à 30. |
| `VIDEO_BITRATE` | `6000k` | Débit vidéo cible ; entier positif avec suffixe facultatif `k` ou `M`. |
| `ENCODER_PRESET` | `veryfast` | `ultrafast`, `superfast`, `veryfast`, `faster`, `fast` ou `medium`. Les presets plus lents demandent davantage de CPU. |
| `ENCODER_THREADS` | `4` | Nombre de threads de l'encodeur, de 1 à 16. |
| `RELAY_CPUS` | `5.0` | Quota CPU du relais, distinct du nombre de threads. Ajuster à la capacité disponible. |

Pour commencer en 720p, saisir `WIDTH=1280`, `HEIGHT=720`, `FPS=30` et
`VIDEO_BITRATE=3500k`. Préparer un overlay adapté à cette résolution. Les limites
mémoire (1 536 Mio / 512 Mio) et le quota CPU MediaMTX (`1.0`) sont fixés dans le
Compose : aucune variable dédiée ne permet de les changer actuellement.

### Fichiers et basculement

| Variable | Valeur initiale recommandée | Rôle / valeurs acceptées |
| --- | --- | --- |
| `ASSETS_DIR` | `/opt/basket-live/assets` | Chemin absolu du dossier sur le VPS, monté dans `relay` à `/assets`. La valeur du dépôt `./assets` utilise les fichiers Git. |
| `WAITING_IMAGE` | `/assets/waiting.png` | Chemin dans le conteneur, jamais le chemin `/opt/...` du VPS. |
| `OVERLAY_IMAGE` | `/assets/overlay.png` | Chemin dans le conteneur vers un PNG transparent. |
| `STALE_SECONDS` | `1.5` | Âge maximal en secondes de la dernière image avant passage en attente, de `0.2` à `10`. |
| `READY_FRAMES` | `5` | Nombre d'images reçues avant passage au direct, de `1` à `120`. |
| `OUTPUT_STALL_SECONDS` | `20` | Délai sans progression de l'encodeur avant sa relance, de `5` à `120` secondes. |

Le Compose renseigne lui-même `INPUT_URL=rtsp://mediamtx:8554/live` et construit
`MTX_AUTHINTERNALUSERS` à partir des deux comptes. Ne pas les saisir séparément
dans Coolify. `OUTPUT_URL` est réservé aux tests du contrôleur et n'est pas exposé
par le Compose de production.

## 4. Volumes et fichiers persistants sur le VPS

L'application ne contient ni base de données, ni enregistrement vidéo, ni état
de session à conserver sur disque. Les fichiers à conserver sont les images et,
si vous la personnalisez hors Git, la configuration MediaMTX. Un volume ne
permet pas de préserver la connexion YouTube lors d'un redémarrage.

| Service | Source sur le VPS | Destination dans le conteneur | Mode | Configuration |
| --- | --- | --- | --- | --- |
| `relay` | `/opt/basket-live/assets` | `/assets` | Bind mount, lecture seule | Définir `ASSETS_DIR=/opt/basket-live/assets` ; montage déjà déclaré dans le Compose. |
| `mediamtx` | `./config/mediamtx.yml`, relatif au dépôt déployé | `/mediamtx.yml` | Bind mount de fichier, lecture seule | Montage déjà déclaré ; la configuration est conservée et versionnée dans Git. |
| `mediamtx`, variante facultative | `/opt/basket-live/config/mediamtx.yml` | `/mediamtx.yml` | Bind mount de fichier, lecture seule | Remplacer la source du montage existant par ce chemin absolu dans la configuration Compose déployée. |

Pour le déploiement recommandé, seul le dossier des images est à créer en dehors
du répertoire Git de Coolify. Ne pas monter un volume nommé vide à `/assets` :
les deux PNG doivent être présents dès le démarrage. Ne pas créer de volume
persistant à `/tmp` : le Compose y prévoit un `tmpfs` de 32 Mio pour les fichiers
temporaires et le heartbeat. Les journaux sont sur stdout/stderr, avec une rotation
Docker de trois fichiers de 10 Mo par service ; aucun volume de logs applicatifs
n'est nécessaire.

### Préparer le dossier des images

Exécuter sur le VPS cible, depuis une copie du dépôt contenant les PNG (ou adapter
les chemins sources à l'emplacement de vos propres fichiers) :

```sh
sudo install -d -m 0755 /opt/basket-live /opt/basket-live/assets
sudo install -m 0644 assets/waiting.png /opt/basket-live/assets/waiting.png
sudo install -m 0644 assets/overlay.png /opt/basket-live/assets/overlay.png
sudo ls -ld /opt/basket-live /opt/basket-live/assets
sudo ls -l /opt/basket-live/assets/waiting.png /opt/basket-live/assets/overlay.png
```

Ces commandes copient les exemples et remplacent les fichiers de même nom :
sur une installation existante, conserver vos images personnalisées. Utiliser
une attente en 1920×1080 pour le profil par défaut et un overlay PNG RGBA
transparent. L'overlay est posé en haut à gauche sans redimensionnement.

Le relais fonctionne avec l'UID/GID `10001:10001`. Les droits `0755` sur les
dossiers et `0644` sur les PNG permettent la lecture sans lui donner de droits
d'écriture ; vérifier aussi la traversée des éventuels dossiers parents. Il n'est
pas nécessaire de changer le propriétaire en `10001` ni de donner les droits `777`.

Dans Coolify, vérifier après résolution du Compose que le service `relay` utilise
bien la source absolue souhaitée. Les fichiers doivent exister sur le serveur
Docker, pas seulement sur la machine qui héberge l'interface Coolify. Après un
changement d'image PNG, redémarrer le relais : l'attente est préchargée et l'overlay
est ouvert au démarrage de l'encodeur. Cette opération coupe la connexion RTMPS.

### Variante : configuration MediaMTX indépendante de Git

La configuration fournie par Git suffit au déploiement standard. Pour la gérer
sur le VPS, créer d'abord le fichier :

```sh
sudo install -d -m 0755 /opt/basket-live/config
sudo install -m 0644 config/mediamtx.yml /opt/basket-live/config/mediamtx.yml
```

Remplacer ensuite le montage existant de `mediamtx` dans le Compose déployé
(dans votre fork ou l'éditeur Compose Coolify si disponible) :

```yaml
volumes:
  - type: bind
    source: /opt/basket-live/config/mediamtx.yml
    target: /mediamtx.yml
    read_only: true
```

Il s'agit d'un fichier, pas d'un dossier. Ne pas conserver en parallèle l'ancien
montage à la même destination. Il n'existe pas de variable `MEDIAMTX_CONFIG` dans
le Compose actuel : ajouter une telle variable dans Coolify ne change pas ce
montage. Garder l'authentification via `MTX_AUTHINTERNALUSERS` et les variables
Coolify, sans ajouter les vrais mots de passe dans le YAML. Redéployer après une
modification de configuration et vérifier que les mises à jour depuis Git
conservent le montage souhaité.

### Sauvegardes

Sauvegarder `/opt/basket-live/assets`, le dossier `config` si cette variante est
utilisée, ainsi que la configuration et les secrets Coolify selon votre procédure
de sauvegarde. Conserver une copie hors du VPS : un bind mount survit aux
redéploiements mais pas à la perte du disque. Conserver aussi la référence exacte
de `RELAY_IMAGE`. Lors d'une restauration, remettre les fichiers et leurs droits
sur le serveur cible avant de déployer.

## 5. Réseau et premier lancement

| Sens | Port | Action |
| --- | --- | --- |
| Entrant public | TCP `1935`, ou la valeur de `RTMP_PORT` | Autoriser dans le pare-feu du fournisseur/VPS et le filtrage Docker ; aucune autre application ne doit utiliser ce port. |
| Interne Docker | TCP `8554` sur `mediamtx` | Conserver privé ; aucun port hôte à ouvrir. |
| Sortant | TCP `443` | Autoriser le téléchargement des images depuis les registres et la diffusion RTMPS YouTube. |
| Sortant | DNS selon la configuration du VPS | Permettre la résolution des noms. |

Le filtrage des ports publiés par Docker peut contourner les règles UFW ;
vérifier aussi le pare-feu du fournisseur (OVH si utilisé) et `DOCKER-USER`.
Les accès d'administration Coolify/SSH du VPS restent à gérer suivant votre
installation. Aucun domaine, certificat HTTP ou port UDP supplémentaire n'est
requis par cette application. RTMP entrant est en clair : le téléphone reçoit
uniquement son compte de publication, jamais la clé YouTube.

1. Enregistrer les variables, vérifier les montages et cliquer sur **Deploy**.
2. Vérifier les logs de téléchargement des deux images, puis les logs des services.
   Le relais émet immédiatement l'attente et le silence vers YouTube.
3. Vérifier que `relay` devient sain après le délai de démarrage (30 secondes dans
   le Compose), puis vérifier la prévisualisation dans YouTube Studio. Cliquer sur
   « Passer au direct » si le démarrage manuel est activé.
4. Configurer le téléphone avec
   `rtmp://ADRESSE_DU_VPS:1935/live?user=phone&pass=MOT_DE_PASSE` en remplaçant
   le port, l'utilisateur et le mot de passe par vos valeurs. Le chemin reste `live`.
5. Publier puis arrêter la publication du téléphone. Vérifier les transitions
   match/attente dans Studio et les logs `switch state=live` / `switch state=waiting`.
   `output_started` doit rester unique pendant ces transitions normales.
6. Contrôler CPU et mémoire dans Coolify pendant un essai représentatif avant un
   match. `scheduler_overrun` invite à réduire la résolution ou la charge CPU.

Pour terminer une session, arrêter le relais puis terminer explicitement
l'événement dans YouTube Studio. Un redéploiement ou un changement de variables
qui recrée le relais impose une nouvelle connexion ; un événement clôturé ne se
rouvre pas automatiquement.

## 6. Vérifications en cas d'échec

| Symptôme | Vérification |
| --- | --- |
| `Set ...` pendant la résolution Compose | Variable obligatoire absente ou vide dans l'environnement de production Coolify. |
| Image introuvable / accès refusé | Image publiée, référence `RELAY_IMAGE` exacte et accès Docker Hub configuré si privé. |
| Échec de lecture des PNG | `ASSETS_DIR` absolu sur le bon VPS, deux fichiers présents, noms et droits corrects ; chemins `/assets/...` dans le conteneur. |
| MediaMTX refuse `/mediamtx.yml` | Source existante de type fichier ; aucun montage concurrent sur cette destination. |
| Téléphone refusé ou inaccessible | IP/port, pare-feu, compte de publication, chemin `live` ; un autre téléphone ne doit pas déjà publier sur ce chemin. |
| Match reçu mais absent sur YouTube | Logs du relais, clé et URL RTMPS, accès sortant, état de l'événement Studio. |
| `output_lost` ou relais malsain | Connexion sortante, progression de l'encodeur et ressources disponibles ; les volumes ne corrigent pas ces ruptures. |

Pour les tests synthétiques et les limites de continuité, voir le
[README](../README.md), la [validation](validation.md) et
l'[architecture](architecture.md). Ne pas partager de rendu Compose résolu,
de dump Docker ou de logs contenant des URL de connexion avec des secrets.
