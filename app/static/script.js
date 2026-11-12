/* Interface française du convertisseur, sans dépendance JavaScript externe. */
const $ = (selector) => document.querySelector(selector);
const fileInput = $('#file-input');
const dropZone = $('#drop-zone');
const fileList = $('#file-list');
const files = [];
const successfulBatches = new Set();
let activeMarkdown = '';
let currentBatchId = null;

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / 1024 ** 2).toFixed(1)} Mo`;
}
function setTheme(theme) { document.documentElement.dataset.theme = theme; localStorage.setItem('theme', theme); }
const savedTheme = localStorage.getItem('theme');
if (savedTheme) setTheme(savedTheme);
$('#theme-toggle').addEventListener('click', () => setTheme((document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark' ? 'light' : 'dark'));

async function loadFormats() {
  try {
    const response = await fetch('/api/supported-extensions');
    const data = await response.json();
    $('#extensions').textContent = data.extensions.join(' · ');
    if (!data.youtube) {
      $('#youtube-convert').disabled = true;
      $('#youtube-status').textContent = 'Composant manquant : fermez puis relancez demarrer.bat pour l’installer.';
      $('#youtube-status').classList.add('error');
    }
  } catch { $('#extensions').textContent = 'Impossible de charger la liste des formats.'; }
}
loadFormats();

function addFiles(selected) {
  for (const file of selected) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (!files.some(item => item.key === key)) files.push({ file, key, status: 'pending' });
  }
  renderFiles();
}
$('#choose-button').addEventListener('click', (event) => { event.stopPropagation(); fileInput.click(); });
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } });
fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });
for (const eventName of ['dragenter', 'dragover']) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.add('dragover'); });
for (const eventName of ['dragleave', 'drop']) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.remove('dragover'); });
dropZone.addEventListener('drop', (event) => addFiles(event.dataTransfer.files));

function renderFiles() {
  fileList.replaceChildren();
  files.forEach((item, index) => {
    const file = item.file;
    const card = document.createElement('article'); card.className = 'file-card';
    const icon = document.createElement('div'); icon.className = 'file-icon'; icon.textContent = file.name.split('.').pop().slice(0, 5);
    const info = document.createElement('div'); info.className = 'file-info';
    const name = document.createElement('div'); name.className = 'file-name'; name.textContent = file.name;
    const meta = document.createElement('div'); meta.className = 'file-meta'; meta.textContent = `${(file.name.split('.').pop() || 'fichier').toUpperCase()} · ${formatSize(file.size)}`;
    info.append(name, meta);
    const status = document.createElement('div'); status.className = `file-status ${item.status === 'success' ? 'success' : item.status === 'error' ? 'error' : item.status === 'running' ? 'running' : ''}`;
    if (item.status === 'running') { const spinner = document.createElement('span'); spinner.className = 'spinner'; status.append(spinner, 'Conversion en cours'); }
    else status.textContent = item.status === 'success' ? '✓ Conversion réussie' : item.status === 'error' ? `Erreur · ${item.error}` : 'En attente';
    card.append(icon, info, status);
    if (item.status === 'running') { const progress = document.createElement('div'); progress.className = 'file-progress'; progress.innerHTML = '<span></span>'; card.append(progress); }
    if (item.status === 'success') {
      const tools = document.createElement('div'); tools.className = 'file-tools';
      const preview = makeAction('Aperçu', '◉', () => showPreview(item));
      const copy = makeAction('Copier le Markdown', '▣', () => copyText(item.markdown));
      const download = makeAction('Télécharger', '↓', () => { location.href = `/api/download/${item.conversionId}`; });
      tools.append(preview, copy, download); card.append(tools);
    }
    fileList.append(card);
  });
  const count = files.length;
  $('#file-count').textContent = count ? `${count} fichier${count > 1 ? 's' : ''} ajouté${count > 1 ? 's' : ''}` : 'Aucun fichier ajouté';
  $('#convert-button').disabled = !count || files.some(item => item.status === 'running') || files.every(item => item.status === 'success');
  $('#clear-button').disabled = !count;
  $('#zip-button').disabled = successfulBatches.size === 0;
}
function makeAction(label, icon, action) { const button = document.createElement('button'); button.className = 'small-action'; button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.textContent = icon; button.addEventListener('click', action); return button; }
async function copyText(text) { try { await navigator.clipboard.writeText(text); } catch { const area = document.createElement('textarea'); area.value = text; document.body.append(area); area.select(); document.execCommand('copy'); area.remove(); } }
function showPreview(item) {
  activeMarkdown = item.markdown; $('#preview-title').textContent = `${item.file.name.replace(/\.[^.]+$/, '')}.md`;
  $('#preview-content').textContent = activeMarkdown; $('#preview-download').href = `/api/download/${item.conversionId}`;
  $('#preview-panel').classList.remove('hidden'); $('#preview-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$('#preview-copy').addEventListener('click', () => copyText(activeMarkdown));
$('#close-preview').addEventListener('click', () => $('#preview-panel').classList.add('hidden'));
$('#clear-button').addEventListener('click', () => { files.splice(0); successfulBatches.clear(); currentBatchId = null; $('#errors-list').replaceChildren(); $('#errors-panel').classList.add('hidden'); $('#preview-panel').classList.add('hidden'); renderFiles(); });

$('#convert-button').addEventListener('click', async () => {
  $('#errors-list').replaceChildren(); $('#errors-panel').classList.add('hidden');
  const pending = files.filter(item => item.status === 'pending' || item.status === 'error');
  if (pending.length && !currentBatchId) currentBatchId = crypto.randomUUID().replaceAll('-', '');
  // Une requête par fichier permet d'afficher fidèlement l'état de progression.
  for (const item of pending) {
    item.status = 'running'; item.error = ''; renderFiles();
    const body = new FormData(); body.append('files', item.file, item.file.name);
    try {
      const response = await fetch(`/api/convert?batch_id=${encodeURIComponent(currentBatchId)}`, { method: 'POST', body });
      const payload = await response.json();
      const result = payload.results?.[0];
      if (!response.ok || !result) throw new Error(payload.detail || 'La conversion a échoué.');
      if (result.status === 'success') {
        const previewResponse = await fetch(`/api/preview/${result.conversion_id}`);
        if (!previewResponse.ok) throw new Error('Conversion créée, mais aperçu local indisponible.');
        const previewData = await previewResponse.json();
        Object.assign(item, { status: 'success', conversionId: result.conversion_id, markdown: previewData.markdown });
        successfulBatches.add(payload.batch_id);
      } else { item.status = 'error'; item.error = result.error; addError(item.file.name, result.error); }
    } catch (error) { item.status = 'error'; item.error = error.message || 'Erreur de communication avec le serveur local.'; addError(item.file.name, item.error); }
    renderFiles();
  }
});
function addError(filename, message) {
  const li = document.createElement('li'); li.textContent = `${filename} : ${message}`; $('#errors-list').append(li); $('#errors-panel').classList.remove('hidden');
}
$('#zip-button').addEventListener('click', () => {
  // Chaque requête de conversion forme son propre lot (le traitement reste séquentiel).
  // On déclenche une archive contenant les fichiers réussis, regroupés côté client si plusieurs lots.
  if (successfulBatches.size === 1) location.href = `/api/download-zip/${[...successfulBatches][0]}`;
  else downloadCombinedZip();
});
async function downloadCombinedZip() {
  if (currentBatchId) location.href = `/api/download-zip/${currentBatchId}`;
}
$('#youtube-convert').addEventListener('click', async () => {
  const button = $('#youtube-convert');
  const url = $('#youtube-url').value.trim();
  const status = $('#youtube-status');
  status.className = 'youtube-status running';
  status.textContent = 'Récupération de la transcription…';
  button.disabled = true;
  try {
    const response = await fetch('/api/convert-youtube', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, batch_id: currentBatchId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'La conversion YouTube a échoué.');
    const result = payload.result;
    const previewResponse = await fetch(`/api/preview/${result.conversion_id}`);
    if (!previewResponse.ok) throw new Error('La transcription a été créée, mais son aperçu est indisponible.');
    const previewData = await previewResponse.json();
    currentBatchId = payload.batch_id;
    successfulBatches.add(payload.batch_id);
    files.push({
      key: `youtube:${result.conversion_id}`,
      file: { name: result.filename, size: result.size },
      status: 'success', conversionId: result.conversion_id, markdown: previewData.markdown,
    });
    renderFiles();
    status.className = 'youtube-status success';
    status.textContent = 'Transcription ajoutée à votre liste de conversions.';
    $('#youtube-url').value = '';
  } catch (error) {
    status.className = 'youtube-status error';
    status.textContent = error.message || 'Erreur pendant la récupération de la transcription.';
  } finally {
    button.disabled = false;
  }
});
renderFiles();
