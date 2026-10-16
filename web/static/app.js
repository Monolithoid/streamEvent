'use strict';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let model, previewUrl, timer, controller, generation = 0, dirty = false, publishedHash, publishedAt;
window.addEventListener('error', event => message('Erreur de la console : ' + event.message));
window.addEventListener('unhandledrejection', event => message('Erreur de la console : ' + (event.reason?.message || event.reason)));
async function api(path, body, signal) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', signal,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (response.status === 401) {location.assign('/login'); throw new Error('Connexion expirée.');}
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = response.status === 403 ? 'Session invalide : rechargez la page puis reconnectez-vous.' : `Requête ${path} refusée (HTTP ${response.status}).`;
    throw new Error(error.error || detail);
  }
  return response;
}
function message(text) {$('message').textContent = text;}
function changed() {
  dirty = true;
  message('Modifications en attente de validation.');
  $('publish').disabled = false;
  clearTimeout(timer);
  controller?.abort();
  const current = ++generation;
  timer = setTimeout(async () => {
    controller = new AbortController();
    try {
      const response = await api('/api/preview', model, controller.signal);
      const blob = await response.blob();
      if (current !== generation) return;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob); $('preview').src = previewUrl;
      message('Aperçu actualisé · modifications en attente de validation.');
    } catch (e) {if (e.name !== 'AbortError' && current === generation) message(e.message);}
  }, 350);
}
function field(zone, key, title, type = 'text') {
  const label = document.createElement('label'); label.textContent = title;
  const input = document.createElement(key === 'text' ? 'textarea' : 'input');
  if (input.tagName === 'INPUT') input.type = type;
  input.value = zone[key];
  if (type === 'number') {input.min = key === 'size' ? 8 : ['width','height'].includes(key) ? 1 : 0; input.max = key === 'size' ? 160 : ['x','width'].includes(key) ? model.width : model.height;}
  if (key === 'text') input.maxLength = 500;
  if (key === 'label') input.maxLength = 60;
  input.addEventListener('input', () => {zone[key] = type === 'number' ? Number(input.value) : input.value; changed();});
  label.append(input); return label;
}
function drawEditor() {
  $('zones').replaceChildren(); $('empty').hidden = model.zones.length !== 0;
  $('add').disabled = model.zones.length >= 24;
  model.zones.forEach((zone, index) => {
    const block = document.createElement('article'); block.className = 'zone';
    const head = document.createElement('div'); head.className = 'zonehead'; head.append(field(zone, 'label', 'Nom de la zone (éditeur uniquement)'));
    const remove = document.createElement('button'); remove.textContent = 'Supprimer'; remove.className = 'danger';
    remove.onclick = () => {model.zones.splice(index,1); drawEditor(); changed();}; head.append(remove); block.append(head, field(zone,'text','Texte affiché'));
    const grid = document.createElement('div'); grid.className = 'grid';
    for (const [key,label] of [['x','Position X'],['y','Position Y'],['size','Taille du texte'],['width','Largeur'],['height','Hauteur']]) grid.append(field(zone,key,label,'number'));
    block.append(grid,field(zone,'color','Texte · #RRGGBBAA'),field(zone,'background','Fond · #RRGGBBAA (00 = transparent)'));
    $('zones').append(block);
  });
}
function newZone(label, text, x, y, width, height, size) {
  return {label,text,x,y,width: Math.min(width,model.width-x),height: Math.min(height,model.height-y),size,color:'#FFFFFFFF',background:'#10151BE6'};
}
$('add').onclick = () => {model.zones.push(newZone('Nouvelle zone','Votre texte',0,0,500,100,36));drawEditor();changed();};
$('preset').onclick = () => {
  const w = model.width, h = model.height, scale = Math.min(w/1920,h/1080);
  const z = (label,text,x,y,width,height,size) => newZone(label,text,Math.floor(x*scale),Math.floor(y*scale),Math.max(1,Math.floor(width*scale)),Math.max(1,Math.floor(height*scale)),Math.max(8,Math.floor(size*scale)));
  model.zones.push(z('Équipe domicile','DOMICILE   0',50,40,600,90,42),z('Équipe visiteuse','0   VISITEURS',650,40,600,90,42),z('Événement','Nom de l’événement · Quart-temps 1',50,140,1200,65,28));
  drawEditor();changed();
};
$('publish').onclick = async () => {
  $('publish').disabled = true;
  // Freeze this version while the request is in flight; preserve later edits.
  const version = generation;
  try {
    const state = await (await api('/api/overlay', model)).json();
    model.revision = state.revision;
    publishedHash = state.sha256; publishedAt = Date.now(); $('delivery').textContent = 'Vérification de la réception du PNG par le relais…';
    $('lastUpdate').textContent = 'Dernière validation : ' + new Date(state.updated_at*1000).toLocaleTimeString('fr-FR');
    if (version === generation) {dirty = false;message('Overlay enregistré. Le statut ci-dessous confirme sa réception par le relais.');}
    else message('Version validée. De nouvelles modifications restent à diffuser.');
  } catch(e) {message(e.message);} finally {$('publish').disabled = !dirty;}
};
$('logout').onclick = async () => {try {await api('/logout',{});location.assign('/login');} catch(e) {message(e.message);}};
function connectionField(title, value, secret = false) {
  const label = document.createElement('label'); label.textContent = title;
  const row = document.createElement('div'); row.className = 'copy-row';
  const input = document.createElement('input'); input.value = value; input.readOnly = true;
  input.type = secret ? 'password' : 'text'; input.autocomplete = 'off'; input.spellcheck = false;
  row.append(input);
  if (secret) {
    const reveal = document.createElement('button'); reveal.className = 'secondary'; reveal.textContent = 'Afficher';
    reveal.type = 'button'; reveal.setAttribute('aria-label', 'Afficher ' + title);
    reveal.onclick = () => {input.type = input.type === 'password' ? 'text' : 'password'; reveal.textContent = input.type === 'password' ? 'Afficher' : 'Masquer';};
    row.append(reveal);
  }
  const copy = document.createElement('button'); copy.className = 'secondary'; copy.textContent = 'Copier'; copy.type = 'button';
  copy.setAttribute('aria-label', 'Copier ' + title);
  copy.onclick = async () => {
    try {await navigator.clipboard.writeText(value); $('copy-message').textContent = title + ' copié.';}
    catch {input.type = 'text';input.focus();input.select();$('copy-message').textContent = 'Copie automatique indisponible : le champ est sélectionné, utilisez la commande Copier.';}
  };
  row.append(copy); label.append(row); return label;
}
async function loadIngest() {
  try {
    const settings = await (await api('/api/ingest')).json();
    $('ingest-help').textContent = settings.authentication ? 'Renseignez le serveur, la clé, puis activez l’authentification dans votre application.' : 'Renseignez le serveur et la clé dans votre application. Laissez l’authentification désactivée.';
    const fields = [connectionField('URL du serveur',settings.server_url),connectionField('Clé de flux',settings.stream_key,true)];
    if (settings.authentication) fields.push(connectionField('Identifiant',settings.username),connectionField('Mot de passe',settings.password,true));
    $('ingest-fields').replaceChildren(...fields);
  } catch(e) {$('ingest-help').textContent = e.message;}
}
let broadcastPending = false;
for (const [id, enabled] of [['start-broadcast', true], ['stop-broadcast', false]]) {
  $(id).onclick = async () => {
    broadcastPending = true;
    $('start-broadcast').disabled = $('stop-broadcast').disabled = true;
    try {
      await api('/api/broadcast', {enabled});
      $('broadcast-message').textContent = enabled ? 'Démarrage demandé…' : 'Arrêt demandé…';
    } catch (e) {$('broadcast-message').textContent = e.message;}
    finally {broadcastPending = false;}
  };
}
async function status() {
  try {
    const s = await (await api('/api/status')).json();
    if (publishedHash) {
      if (s.stale) $('delivery').textContent = 'Statut du relais indisponible : réception du PNG non confirmée.';
      else if (s.broadcast_enabled === false) $('delivery').textContent = 'Overlay enregistré. Sa réception sera confirmée au démarrage de la diffusion YouTube.';
      else if (!s.overlay_sha256) $('delivery').textContent = 'Le relais ne fournit pas la confirmation du PNG. Mettez web et relay à jour avec la même image Docker.';
      else if (s.overlay_sha256 === publishedHash) $('delivery').textContent = 'Le relais voit le PNG validé. Prévoir quelques secondes de relecture, puis le délai de la plateforme vidéo.';
      else if (Date.now() - publishedAt > 10000) $('delivery').textContent = 'Le relais ne voit pas le PNG validé. Vérifiez que web et relay partagent le même volume overlay-data et le chemin /data/overlay/overlay.png.';
    }
    const available = !s.stale && Boolean(s.run_id) && typeof s.broadcast_enabled === 'boolean';
    $('start-broadcast').disabled = broadcastPending || !available || s.broadcast_enabled;
    $('stop-broadcast').disabled = broadcastPending || !available;
    if (!broadcastPending) $('broadcast-message').textContent = !available ? 'Commande indisponible : vérifiez le relais et sa version.' : s.broadcast_enabled ? (s.output_healthy ? 'Diffusion vers YouTube active.' : 'Connexion à YouTube en cours…') : 'Diffusion YouTube arrêtée.';
    $('connection').textContent = s.stale ? 'Statut indisponible' : '● Relais connecté';
    $('state').textContent = s.stale ? 'Inconnue' : s.state === 'live' ? 'Caméra en direct' : 'Image d’attente';
    $('output').textContent = s.stale ? 'Inconnue' : s.broadcast_enabled === false ? 'YouTube arrêté' : s.output_healthy ? 'Encodage actif' : 'Reconnexion…';
    $('format').textContent = s.stale ? '—' : `${s.width} × ${s.height} · ${s.fps} ips`;
    $('bitrate').textContent = s.stale ? '—' : s.video_bitrate;
  } catch(e) {$('start-broadcast').disabled = $('stop-broadcast').disabled = true; $('broadcast-message').textContent = 'Statut de diffusion indisponible.'; $('connection').textContent = 'Statut indisponible'; for (const id of ['state','output','format','bitrate']) $(id).textContent = '—';}
}
(async () => {
  try {model = await (await api('/api/overlay')).json(); $('dimensions').textContent = `${model.width} × ${model.height} · ALPHA`; $('preview').src = '/api/overlay.png';drawEditor();$('preset').disabled = false;$('publish').disabled = true;publishedHash = model.sha256;publishedAt = Date.now();message('Éditeur prêt · ajoutez ou modifiez une zone pour préparer la suite.');if(model.updated_at) $('lastUpdate').textContent = 'Dernière validation : ' + new Date(model.updated_at*1000).toLocaleTimeString('fr-FR');}
  catch(e) {message(e.message);$('add').disabled = true;$('preset').disabled = true;$('publish').disabled = true;}
  await Promise.all([status(), loadIngest()]);setInterval(status,3000);
})();
window.addEventListener('beforeunload', e => {if(dirty) {e.preventDefault();e.returnValue = '';}});
