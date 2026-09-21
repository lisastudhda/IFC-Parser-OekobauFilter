"""Small web interface for uploading and inspecting IFC extraction results."""

from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request, send_file

from .csv_export import CSVExporter
from .ifc_parser import IfcParser
from .oekobaudat_processor import OekobaudatProcessor, _format_german_float
from .quantity_extractor import QuantityExtractor


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024

PAGE = r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IFC & Ökobaudat LCA Tool</title>
  <style>
    :root { --ink: #17211b; --muted: #65736a; --line: #d8dfd8; --paper: #f5f7f2; --accent: #d65a35; --accent-dark: #a83f23; --success: #2e7d32; --warning: #c67c00; }
    * { box-sizing: border-box; }
    body { margin: 0; color: var(--ink); background: radial-gradient(circle at 12% 0%, #e9f0e5 0, transparent 34%), var(--paper); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    main { width: min(1200px, calc(100% - 40px)); margin: 0 auto; padding: 40px 0 70px; }
    header { display: flex; justify-content: space-between; gap: 30px; align-items: end; margin-bottom: 24px; }
    h1 { max-width: 650px; margin: 0; font-size: clamp(2rem, 5vw, 3.8rem); line-height: 1.05; letter-spacing: -0.02em; font-weight: 600; }
    .kicker { margin: 0 0 8px; color: var(--accent-dark); font: 700 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; text-transform: uppercase; }
    .intro { max-width: 320px; color: var(--muted); margin: 0; font-size: 14px; }
    
    .nav-tabs { display: flex; gap: 4px; border-bottom: 2px solid var(--line); margin-bottom: 24px; }
    .nav-tabs button { background: transparent; border: none; border-bottom: 3px solid transparent; color: var(--muted); padding: 12px 20px; font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; cursor: pointer; transition: all 0.2s; }
    .nav-tabs button.active { color: var(--accent-dark); border-bottom-color: var(--accent); background: rgba(255,255,255,0.6); }
    
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    .dropzone { border: 2px dashed #9cae9e; background: rgba(255,255,255,.68); padding: 36px 24px; text-align: center; transition: border-color .2s, background .2s, transform .2s; border-radius: 4px; }
    .dropzone.is-over { border-color: var(--accent); background: #fff6ee; transform: translateY(-2px); }
    .dropzone h2 { margin: 0 0 6px; font-size: 1.5rem; font-weight: 500; }
    .dropzone p { margin: 0 0 18px; color: var(--muted); font-size: 14px; }
    button, .file-label { border: 0; background: var(--accent); color: white; padding: 10px 18px; cursor: pointer; font: 700 13px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; border-radius: 3px; display: inline-block; }
    button:hover, .file-label:hover { background: var(--accent-dark); }
    button:disabled { background: #b5c2b7; cursor: not-allowed; }
    input[type=file] { display: none; }
    .status-msg { min-height: 24px; margin: 16px 0; color: var(--muted); font-weight: 500; font-size: 14px; }
    
    .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); margin-bottom: 20px; }
    .stat { background: white; padding: 14px 18px; }
    .stat strong { display: block; font-size: 1.6rem; font-weight: 600; color: var(--ink); }
    .stat span { color: var(--muted); font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; }
    
    .view-switch { display: flex; gap: 8px; margin: 20px 0 12px; align-items: center; flex-wrap: wrap; }
    .view-switch button { background: #dce5dc; color: var(--ink); }
    .view-switch button.active { background: var(--accent); color: white; }
    
    .filter-panel { background: white; border: 1px solid var(--line); padding: 20px; margin-bottom: 20px; border-radius: 4px; }
    .filter-grid { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 16px; align-items: end; }
    .form-group { display: flex; flex-direction: column; gap: 6px; }
    .form-group label { font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; color: var(--muted); }
    .form-group input { padding: 9px 12px; border: 1px solid #c1cdc2; border-radius: 3px; font-size: 14px; }
    
    .table-wrap { overflow: auto; border: 1px solid var(--line); background: white; max-height: 580px; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #e7ebe7; text-align: left; white-space: nowrap; font-size: 13px; }
    th { color: var(--muted); background: #f0f3ee; font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; position: sticky; top: 0; z-index: 2; }
    .empty { padding: 34px; text-align: center; color: var(--muted); }
    .badge-ok { color: var(--success); font-weight: bold; }
    .badge-warn { color: var(--warning); font-weight: bold; }

    @media (max-width: 800px) {
      .filter-grid { grid-template-columns: 1fr; }
      header { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <p class="kicker">IFC-LCA Analyse & Ökobaudat Tool</p>
      <h1>Baustoffe & Ökobilanz</h1>
    </div>
    <p class="intro">IFC-Materialien extrahieren oder große Ökobaudat-Datenbanken (CSV bis 250 MB) filtern und GWP-Mittelwerte bilden.</p>
  </header>

  <nav class="nav-tabs">
    <button id="tab-btn-ifc" class="active" type="button">1. IFC Material-Extraktion</button>
    <button id="tab-btn-obd" type="button">2. Ökobaudat Filter & Mittelwerte</button>
  </nav>

  <!-- TAB 1: IFC EXTRACTION -->
  <section id="tab-ifc" class="tab-content active">
    <section id="dropzone-ifc" class="dropzone">
      <h2>IFC-Datei ablegen</h2>
      <p>Unterstützt werden IFC2x3 & IFC4 Dateien bis 250 MB (z. B. Vectorworks).</p>
      <label class="file-label" for="file-input-ifc">IFC-Datei auswählen</label>
      <input id="file-input-ifc" type="file" accept=".ifc,application/x-step" />
    </section>
    <p id="status-ifc" class="status-msg">Noch keine IFC-Datei eingelesen.</p>

    <section id="summary-ifc" class="summary-grid" style="display: none;"></section>

    <nav class="view-switch">
      <button id="detail-button" class="active" type="button">Detail pro Schicht</button>
      <button id="material-button" type="button">Materialsummen</button>
      <div style="margin-left: auto; display: flex; gap: 8px;">
        <button id="export-summary-csv-button" style="background: var(--accent-dark);" type="button" disabled>⬇ Materialsummen CSV</button>
        <button id="export-csv-button" style="background: #46554b;" type="button" disabled>⬇ Schichtendetail CSV</button>
      </div>
    </nav>
    <section id="results-ifc" class="table-wrap">
      <div class="empty">Die extrahierten IFC-Daten erscheinen hier.</div>
    </section>
  </section>

  <!-- TAB 2: ÖKOBAUDAT -->
  <section id="tab-obd" class="tab-content">
    <section id="dropzone-obd" class="dropzone">
      <h2>Ökobaudat CSV-Datei ablegen</h2>
      <p>Ziehe die große Ökobaudat-Gesamtdatei (z. B. 50 MB) per Drag & Drop hier hinein.</p>
      <label class="file-label" for="file-input-obd">CSV auswählen</label>
      <input id="file-input-obd" type="file" accept=".csv,text/csv" />
    </section>
    <p id="status-obd" class="status-msg">Noch keine Ökobaudat-CSV geladen.</p>

    <div id="filter-panel-obd" class="filter-panel" style="display: none;">
      <div class="filter-grid">
        <div class="form-group">
          <label for="search-keywords">Suchbegriffe / Baustoffe (kommagetrennt)</label>
          <input id="search-keywords" type="text" placeholder="z. B. Kalksandstein, Schaumglas, Beton" value="Kalksandstein" />
        </div>
        <div class="form-group">
          <label for="tolerance-input">Toleranzgrenze (%)</label>
          <input id="tolerance-input" type="number" value="15" min="1" max="100" step="1" />
        </div>
        <div class="form-group">
          <label for="modules-input">Lebenszyklus-Module</label>
          <input id="modules-input" type="text" value="A1-A3, A4, A5" placeholder="A1-A3, A4, A5" />
        </div>
        <div>
          <button id="btn-run-filter" type="button" style="width: 100%;">Filtern & Berechnen</button>
        </div>
      </div>
    </div>

    <section id="summary-obd" class="summary-grid" style="display: none;"></section>

    <nav id="switch-obd" class="view-switch" style="display: none;">
      <button id="btn-view-summary" class="active" type="button">Vermittelte GWP-Werte (Module)</button>
      <button id="btn-view-raw" type="button">Gefilterte Einzel-Datensätze</button>
      <div style="margin-left: auto; display: flex; gap: 8px;">
        <button id="btn-dl-summary" style="background: var(--accent-dark);" type="button">⬇ Summary CSV</button>
        <button id="btn-dl-filtered" style="background: #46554b;" type="button">⬇ Gefilterte Roh-CSV</button>
      </div>
    </nav>

    <section id="results-obd" class="table-wrap">
      <div class="empty">Lade eine Ökobaudat CSV hoch und wähle deine Suchbegriffe.</div>
    </section>
  </section>
</main>

<script>
  const tabBtnObd = document.querySelector('#tab-btn-obd');
  const tabBtnIfc = document.querySelector('#tab-btn-ifc');
  const tabObd = document.querySelector('#tab-obd');
  const tabIfc = document.querySelector('#tab-ifc');

  tabBtnObd.addEventListener('click', () => switchTab('obd'));
  tabBtnIfc.addEventListener('click', () => switchTab('ifc'));

  function switchTab(tab) {
    tabBtnObd.classList.toggle('active', tab === 'obd');
    tabBtnIfc.classList.toggle('active', tab === 'ifc');
    tabObd.classList.toggle('active', tab === 'obd');
    tabIfc.classList.toggle('active', tab === 'ifc');
  }

  /* 1. ÖKOBAUDAT LOGIC */
  const dropzoneObd = document.querySelector('#dropzone-obd');
  const fileInputObd = document.querySelector('#file-input-obd');
  const statusObd = document.querySelector('#status-obd');
  const filterPanelObd = document.querySelector('#filter-panel-obd');
  const btnRunFilter = document.querySelector('#btn-run-filter');
  const summaryObd = document.querySelector('#summary-obd');
  const switchObd = document.querySelector('#switch-obd');
  const resultsObd = document.querySelector('#results-obd');
  const btnViewSummary = document.querySelector('#btn-view-summary');
  const btnViewRaw = document.querySelector('#btn-view-raw');
  const btnDlSummary = document.querySelector('#btn-dl-summary');
  const btnDlFiltered = document.querySelector('#btn-dl-filtered');

  let currentObdFile = null;
  let currentObdData = null;

  ['dragenter', 'dragover'].forEach(t => dropzoneObd.addEventListener(t, e => { e.preventDefault(); dropzoneObd.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach(t => dropzoneObd.addEventListener(t, e => { e.preventDefault(); dropzoneObd.classList.remove('is-over'); }));
  dropzoneObd.addEventListener('drop', e => { e.preventDefault(); handleObdFile(e.dataTransfer.files[0]); });
  fileInputObd.addEventListener('change', e => handleObdFile(e.target.files[0]));

  function handleObdFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      statusObd.textContent = 'Bitte eine gültige Ökobaudat-CSV Datei auswählen.';
      return;
    }
    currentObdFile = file;
    statusObd.textContent = `Datei "${file.name}" (${(file.size / (1024*1024)).toFixed(2)} MB) bereit zum Filtern.`;
    filterPanelObd.style.display = 'block';
  }

  btnRunFilter.addEventListener('click', runObdFilter);

  function runObdFilter() {
    if (!currentObdFile) return;
    const keywords = document.querySelector('#search-keywords').value;
    const tolerance = document.querySelector('#tolerance-input').value;
    const modules = document.querySelector('#modules-input').value;

    statusObd.textContent = `Filtere "${currentObdFile.name}" nach "${keywords}"...`;
    btnRunFilter.disabled = true;

    const form = new FormData();
    form.append('file', currentObdFile);
    form.append('keywords', keywords);
    form.append('tolerance', tolerance);
    form.append('modules', modules);

    fetch('/api/obd-filter', { method: 'POST', body: form })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        btnRunFilter.disabled = false;
        if (!ok) throw new Error(data.error || 'Fehler beim Filtern.');
        currentObdData = data;
        renderObdResults(data);
      })
      .catch(err => {
        btnRunFilter.disabled = false;
        statusObd.textContent = `Fehler: ${err.message}`;
        summaryObd.style.display = 'none';
        switchObd.style.display = 'none';
      });
  }

  function renderObdResults(data) {
    statusObd.textContent = `${data.count} Zeilen für Suchbegriff "${data.keywords}" gefunden.`;
    summaryObd.style.display = 'grid';
    switchObd.style.display = 'flex';

    summaryObd.innerHTML = `
      <div class="stat"><strong>${data.count}</strong><span>Gefilterte Zeilen</span></div>
      <div class="stat"><strong>${data.unique_materials}</strong><span>Eindeutige Baustoffe</span></div>
      <div class="stat"><strong>${data.tolerance}%</strong><span>Max. Abweichung</span></div>
    `;

    renderObdView('summary');
  }

  btnViewSummary.addEventListener('click', () => renderObdView('summary'));
  btnViewRaw.addEventListener('click', () => renderObdView('raw'));

  function renderObdView(view) {
    btnViewSummary.classList.toggle('active', view === 'summary');
    btnViewRaw.classList.toggle('active', view === 'raw');

    if (!currentObdData) return;

    if (view === 'summary') {
      const rows = currentObdData.aggregation_table;
      const headers = ['Modul', 'GWP Vermittelt', 'Einheit', 'Innerhalb 15%', 'Abweichung', 'Datensätze', 'GWP Min', 'GWP Max', 'Status'];
      const headHtml = headers.map(h => `<th>${h}</th>`).join('');
      const bodyHtml = rows.map(r => {
        const badgeClass = r.within_tolerance ? 'badge-ok' : 'badge-warn';
        return `
          <tr>
            <td><strong>${escapeHtml(r.module)}</strong></td>
            <td><strong>${escapeHtml(r.mean_gwp != null ? r.mean_gwp : '—')}</strong></td>
            <td>${escapeHtml(r.unit)}</td>
            <td class="${badgeClass}">${r.within_tolerance ? '✓ Ja' : '✗ Nein'}</td>
            <td>${escapeHtml(r.deviation_percent)}%</td>
            <td>${escapeHtml(r.count)}</td>
            <td>${escapeHtml(r.min_gwp != null ? r.min_gwp : '—')}</td>
            <td>${escapeHtml(r.max_gwp != null ? r.max_gwp : '—')}</td>
            <td>${escapeHtml(r.status)}</td>
          </tr>
        `;
      }).join('');
      resultsObd.innerHTML = `<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml || '<tr><td colspan="9">Keine Daten.</td></tr>'}</tbody></table>`;
    } else {
      const rows = currentObdData.raw_sample || [];
      const fields = ['Name_de', 'Modul', 'GWPtotal_A2', 'GWP_A1', 'Rohdichte_kg_m3', 'Bezugsgroesse', 'Bezugseinheit', 'UUID'];
      const headHtml = fields.map(h => `<th>${h}</th>`).join('');
      const bodyHtml = rows.map(r => `<tr>${fields.map(f => `<td>${escapeHtml(r[f] ?? '')}</td>`).join('')}</tr>`).join('');
      resultsObd.innerHTML = `<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml || '<tr><td colspan="8">Keine Datensätze gefunden.</td></tr>'}</tbody></table>`;
    }
  }

  btnDlSummary.addEventListener('click', () => downloadObdCsv('summary'));
  btnDlFiltered.addEventListener('click', () => downloadObdCsv('filtered'));

  function downloadObdCsv(type) {
    if (!currentObdFile) return;
    const keywords = document.querySelector('#search-keywords').value;
    const tolerance = document.querySelector('#tolerance-input').value;
    const modules = document.querySelector('#modules-input').value;

    const form = new FormData();
    form.append('file', currentObdFile);
    form.append('keywords', keywords);
    form.append('tolerance', tolerance);
    form.append('modules', modules);
    form.append('export_type', type);

    fetch('/api/obd-export-csv', { method: 'POST', body: form })
      .then(r => {
        if (!r.ok) throw new Error('Download fehlgeschlagen.');
        return r.blob();
      })
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const kwClean = keywords.replace(/[^a-zA-Z0-9_-]/g, '_');
        a.download = type === 'summary' ? `oekobaudat_${kwClean}_gwp_summary.csv` : `oekobaudat_${kwClean}_gefiltert.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      })
      .catch(err => alert(err.message));
  }

  /* 2. IFC LOGIC */
  const dropzoneIfc = document.querySelector('#dropzone-ifc');
  const fileInputIfc = document.querySelector('#file-input-ifc');
  const statusIfc = document.querySelector('#status-ifc');
  const summaryIfc = document.querySelector('#summary-ifc');
  const resultsIfc = document.querySelector('#results-ifc');
  const detailButton = document.querySelector('#detail-button');
  const materialButton = document.querySelector('#material-button');
  const exportCsvButton = document.querySelector('#export-csv-button');
  const exportSummaryCsvButton = document.querySelector('#export-summary-csv-button');

  const detailFields = ['Bauteil_GUID', 'IfcType', 'Wandtyp_Name', 'Schicht_Index', 'Material_Name_IFC', 'Schichtdicke_m', 'Fläche_m2', 'Volumen_m3', 'Volumen_Ermittlung', 'OmniClass_Code'];
  const materialFields = ['Material_Name', 'Material_Classification_System', 'Material_Classification_Code', 'Classification_Status', 'Element_Count', 'Total_Quantity_Value', 'Quantity_Unit'];

  let currentIfcData = null;
  let currentIfcFile = null;

  ['dragenter', 'dragover'].forEach(t => dropzoneIfc.addEventListener(t, e => { e.preventDefault(); dropzoneIfc.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach(t => dropzoneIfc.addEventListener(t, e => { e.preventDefault(); dropzoneIfc.classList.remove('is-over'); }));
  dropzoneIfc.addEventListener('drop', e => { e.preventDefault(); chooseIfcFile(e.dataTransfer.files[0]); });
  fileInputIfc.addEventListener('change', e => chooseIfcFile(e.target.files[0]));

  detailButton.addEventListener('click', () => showIfcView('detail'));
  materialButton.addEventListener('click', () => showIfcView('material'));
  exportCsvButton.addEventListener('click', () => downloadIfcCsv('detail'));
  exportSummaryCsvButton.addEventListener('click', () => downloadIfcCsv('summary'));

  function chooseIfcFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.ifc')) {
      statusIfc.textContent = 'Bitte eine IFC-Datei auswählen.';
      return;
    }
    currentIfcFile = file;
    const form = new FormData();
    form.append('file', file);
    statusIfc.textContent = file.name + ' wird eingelesen ...';
    exportCsvButton.disabled = true;
    exportSummaryCsvButton.disabled = true;

    fetch('/api/extract', { method: 'POST', body: form })
      .then(response => response.json().then(data => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || 'Extraktion fehlgeschlagen.');
        renderIfc(data);
        exportCsvButton.disabled = false;
        exportSummaryCsvButton.disabled = false;
      })
      .catch(error => {
        statusIfc.textContent = error.message;
        summaryIfc.style.display = 'none';
        exportCsvButton.disabled = true;
        exportSummaryCsvButton.disabled = true;
      });
  }

  function downloadIfcCsv(type) {
    if (!currentIfcFile) return;
    const form = new FormData();
    form.append('file', currentIfcFile);
    form.append('export_type', type || 'detail');
    fetch('/api/export-csv', { method: 'POST', body: form })
      .then(response => {
        if (!response.ok) throw new Error('CSV-Export fehlgeschlagen.');
        return response.blob();
      })
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const stem = currentIfcFile.name.replace(/\.[^/.]+$/, '');
        a.download = type === 'summary' ? `${stem}_material_summary.csv` : `${stem}_lca_extraction.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      })
      .catch(error => alert(error.message));
  }

  function renderIfc(data) {
    currentIfcData = data;
    statusIfc.textContent = data.filename + ' wurde erfolgreich eingelesen.';
    summaryIfc.style.display = 'grid';
    summaryIfc.innerHTML = `
      <div class="stat"><strong>${data.elements}</strong><span>Elemente</span></div>
      <div class="stat"><strong>${data.rows}</strong><span>Materialzeilen</span></div>
      <div class="stat"><strong>${data.materials}</strong><span>Materialien</span></div>
    `;
    showIfcView('detail');
  }

  function showIfcView(view) {
    if (!currentIfcData) return;
    const fields = view === 'detail' ? detailFields : materialFields;
    const rows = view === 'detail' ? currentIfcData.rows_data : currentIfcData.material_summary;
    detailButton.classList.toggle('active', view === 'detail');
    materialButton.classList.toggle('active', view === 'material');
    const head = fields.map(field => `<th>${field}</th>`).join('');
    const body = rows.map(row => `<tr>${fields.map(field => `<td>${escapeHtml(row[field] ?? '')}</td>`).join('')}</tr>`).join('');
    resultsIfc.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${fields.length}">Keine Materialdaten gefunden.</td></tr>`}</tbody></table>`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }
</script>
</body>
</html>
"""


CSV_EXPORT_COLUMNS = [
    "Bauteil_GUID",
    "IfcType",
    "Wandtyp_Name",
    "Schicht_Index",
    "Material_Name_IFC",
    "Schichtdicke_m",
    "Fläche_m2",
    "Volumen_m3",
    "Volumen_Ermittlung",
    "OmniClass_Code",
]

CSV_MATERIAL_SUMMARY_COLUMNS = [
    "Material_Name",
    "Material_Classification_System",
    "Material_Classification_Code",
    "Classification_Status",
    "Element_Count",
    "Total_Quantity_Value",
    "Quantity_Unit",
]


def _build_material_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material_summary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("Material_Name_IFC") or row.get("Material_Name") or "Unknown",
            row.get("Material_Classification_System") or "",
            row.get("OmniClass_Code") or row.get("Material_Classification_Code") or "",
        )
        if key not in material_summary:
            material_summary[key] = {
                "Material_Name": key[0],
                "Material_Classification_System": key[1],
                "Material_Classification_Code": key[2],
                "Classification_Status": row.get("Classification_Status", "needs_confirmation"),
                "Element_Count": 0,
                "Total_Quantity_Value": 0.0,
                "Quantity_Unit": row.get("Quantity_Unit", "m3"),
                "_elements": set(),
            }
        elem_id = row.get("Bauteil_GUID") or row.get("Element_GUID")
        if elem_id:
            material_summary[key]["_elements"].add(elem_id)
        material_summary[key]["Total_Quantity_Value"] += float(row.get("Volumen_m3") or row.get("Quantity_Value") or 0)
    summary_rows = []
    for row in material_summary.values():
        row["Element_Count"] = len(row.pop("_elements"))
        row["Total_Quantity_Value"] = round(row["Total_Quantity_Value"], 6)
        summary_rows.append(row)
    return summary_rows


def _extract_rows(ifc_path: Path) -> list[dict[str, Any]]:
    parser = IfcParser(ifc_path)
    exporter = CSVExporter()
    elements = parser.parse_all_elements()

    # Identify parent GUIDs so we don't double count container/parent elements
    # if their children are already exported individually.
    parent_guids_with_children = {e.parent_guid for e in elements if e.parent_guid}

    for element in elements:
        # If element is an aggregate parent container with sub-elements that are also extracted,
        # and has no explicit layer breakdown or own distinct materials, skip to avoid double counting.
        if element.has_sub_elements and element.ifc_guid in parent_guids_with_children:
            # If it has no own direct materials or it is a pure container, skip
            if not element.material_layers and not element.materials:
                continue

        # Determine element area: NetSideArea, GrossSideArea, or Area
        area_obj = element.quantities.get("NetSideArea") or element.quantities.get("GrossSideArea") or element.quantities.get("Area")
        element_area = area_obj.value if area_obj else None
        
        # 1. Layered element (e.g. wall with composite layer set)
        if element.material_layers:
            for index, layer in enumerate(element.material_layers, 1):
                # Check if layer thickness is 0 and can be resolved from complex quantities
                layer_thickness = layer.thickness
                if not layer_thickness or layer_thickness <= 0:
                    for comp_name, comp_dict in element.complex_layer_quantities.items():
                        if comp_name.lower() in layer.material.name.lower() or layer.material.name.lower() in comp_name.lower():
                            layer_thickness = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length") or 0.0
                            break

                volume = None
                vol_source = "None"
                if element_area and layer_thickness and layer_thickness > 0:
                    volume = QuantityExtractor.calculate_volume_from_layers({layer.material.name: layer_thickness}, element_area).get(layer.material.name, 0)
                    vol_source = "Calculated_Fallback_AxD"
                else:
                    gross_vol = QuantityExtractor.extract_volume_from_quantities(element.quantities)
                    total_thickness = sum(l.thickness for l in element.material_layers)
                    if gross_vol and total_thickness > 0 and layer_thickness > 0:
                        volume = gross_vol * (layer_thickness / total_thickness)
                        vol_source = "Calculated_ThicknessRatio"
                    elif gross_vol:
                        volume = gross_vol / len(element.material_layers)
                        vol_source = "Calculated_VolumeShare"

                exporter.add_raw_layer(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    layer_index=index,
                    material_name=layer.material.name,
                    material_classification=layer.material.classification_ref,
                    material_classification_system=layer.material.classification_system or element.element_classification_system,
                    material_classification_code=layer.material.classification_code or element.element_classification_code,
                    layer_thickness=layer_thickness,
                    element_area=element_area or 0.0,
                    volume_per_layer=volume or 0.0,
                    material_density=layer.material.density,
                    mass_kg=volume * layer.material.density if (volume and layer.material.density) else None,
                    material_composition="Layered composite material",
                    type_name=element.type_name,
                    omniclass_code=layer.material.classification_code or element.element_classification_code,
                    quantity_source=vol_source,
                    constituent_name=layer.material.constituent_name,
                )
        # 2. Single material / constituent elements
        elif element.materials:
            volume = QuantityExtractor.extract_volume_from_quantities(element.quantities)
            num_materials = len(element.materials)

            # Check if materials have constituent fractions defined (e.g. 0.04257778)
            has_fractions = any(m.fraction is not None for m in element.materials)

            # Check total element thickness if available (e.g. Width: 500 mm)
            element_width = None
            if "Width" in element.quantities:
                element_width = element.quantities["Width"].value

            # Prepare list of complex layer quantities ordered by index/occurrence if available
            complex_q_list = list(element.complex_layer_quantities.items())

            for index, material in enumerate(element.materials, 1):
                vol_source = "Explicit" if volume else "None"
                vol_per_mat = None
                mat_fraction = material.fraction
                mat_thickness_mm = None

                # 1. Try matching complex layer quantity by name or keyword
                for comp_name, comp_dict in element.complex_layer_quantities.items():
                    c_low = comp_name.lower()
                    m_low = material.name.lower()
                    if c_low in m_low or m_low in c_low:
                        mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                        break
                    # Fuzzy match words (e.g. 'Gipskarton' matches 'Gypsum Board MT' / 'Gipskartonplatte', 'Dampfsperre' matches 'Vapor Barrier MT')
                    if any(w in m_low or w in c_low for w in ["gips", "gypsum", "dampf", "vapor", "dämm", "insul", "putz", "plaster", "kalk", "lime", "stein", "brick", "clay", "lehm", "beton", "concrete", "holz", "timber", "wood"]):
                        # Check specific keywords
                        if ("gips" in c_low or "gypsum" in c_low) and ("gips" in m_low or "gypsum" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("dampf" in c_low or "vapor" in c_low) and ("dampf" in m_low or "vapor" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("dämm" in c_low or "insul" in c_low) and ("dämm" in m_low or "insul" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("putz" in c_low or "plaster" in c_low) and ("putz" in m_low or "plaster" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("lehm" in c_low or "clay" in c_low) and ("lehm" in m_low or "clay" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break

                # 2. If no name match, check 1:1 positional match with IfcPhysicalComplexQuantity
                if mat_thickness_mm is None and len(complex_q_list) == len(element.materials):
                    comp_name, comp_dict = complex_q_list[index - 1]
                    mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")

                # Calculate volume and determine volume source
                if mat_thickness_mm and element_area and element_area > 0:
                    # User requirement: Layer thickness and volume directly from thickness properties
                    vol_per_mat = (mat_thickness_mm / 1000.0) * element_area
                    vol_source = "Calculated_Fallback_AxD"
                elif volume is not None:
                    if mat_fraction is not None:
                        # Material specifies its exact percentage / fraction of the total volume
                        vol_per_mat = volume * mat_fraction
                        vol_source = "Calculated_ConstituentFraction"
                    elif has_fractions:
                        # If other materials have fractions, calculate remainder
                        known_fractions = sum(m.fraction for m in element.materials if m.fraction is not None)
                        unspecified_count = sum(1 for m in element.materials if m.fraction is None)
                        remaining_fraction = max(0.0, 1.0 - known_fractions)
                        vol_per_mat = volume * (remaining_fraction / unspecified_count)
                        vol_source = "Calculated_ConstituentFractionRemainder"
                    elif num_materials > 1:
                        # Split equally among constituents
                        vol_per_mat = volume / num_materials
                        vol_source = "Calculated_VolumeShare"
                    else:
                        vol_per_mat = volume
                        vol_source = "Explicit"

                # If thickness not directly found, calculate thickness from fraction or volume & area
                if mat_thickness_mm is None:
                    if mat_fraction is not None and element_width is not None and element_width > 0:
                        mat_thickness_mm = element_width * mat_fraction
                    elif vol_per_mat and element_area and element_area > 0:
                        mat_thickness_mm = (vol_per_mat / element_area) * 1000.0
                    elif element_width and num_materials == 1:
                        mat_thickness_mm = element_width

                exporter.add_raw_element(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    material_name=material.name,
                    material_classification=material.classification_ref,
                    material_classification_system=material.classification_system or element.element_classification_system,
                    material_classification_code=material.classification_code or element.element_classification_code,
                    quantity_value=vol_per_mat or 0.0,
                    quantity_unit="m3",
                    quantity_source=vol_source,
                    material_density=material.density,
                    mass_kg=vol_per_mat * material.density if (vol_per_mat and material.density) else None,
                    is_layered=False,
                    material_composition="Single material" if num_materials == 1 else "Constituent set",
                    type_name=element.type_name,
                    omniclass_code=material.classification_code or element.element_classification_code,
                    element_area=element_area,
                    layer_thickness_mm=mat_thickness_mm,
                    layer_index=index,
                    constituent_name=material.constituent_name,
                )
        # 3. Element with quantities but no explicit material association
        elif element.quantities:
            volume = QuantityExtractor.extract_volume_from_quantities(element.quantities)
            if volume:
                exporter.add_raw_element(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    material_name="Unspecified",
                    material_classification=None,
                    material_classification_system=element.element_classification_system,
                    material_classification_code=element.element_classification_code,
                    quantity_value=volume,
                    quantity_unit="m3",
                    quantity_source="Explicit",
                    material_density=None,
                    mass_kg=None,
                    is_layered=False,
                    material_composition="Unknown",
                    type_name=element.type_name,
                    omniclass_code=element.element_classification_code,
                )

    for row in exporter.data:
        has_classification = bool(
            row.get("Material_Classification_System")
            and row.get("Material_Classification_Code")
        ) or bool(row.get("OmniClass_Code"))
        row["Classification_Status"] = "provided" if has_classification else "needs_confirmation"
    return exporter.data


@app.get("/")
def index() -> str:
    return render_template_string(PAGE)


@app.post("/api/obd-filter")
def obd_filter() -> Any:
    """Filtert die hochgeladene Ökobaudat CSV und berechnet GWP-Mittelwerte."""
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Keine Ökobaudat-CSV erhalten."), 400

    keywords_raw = request.form.get("keywords", "")
    tolerance_raw = request.form.get("tolerance", "15.0")
    modules_raw = request.form.get("modules", "A1-A3, A4, A5")

    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    if not keywords:
        return jsonify(error="Bitte mindestens einen Suchbegriff eingeben."), 400

    try:
        tolerance = float(tolerance_raw)
    except ValueError:
        tolerance = 15.0

    modules = [m.strip().upper() for m in modules_raw.split(",") if m.strip()]

    try:
        processor = OekobaudatProcessor(delimiter=";")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / Path(uploaded.filename).name
            uploaded.save(path)

            filtered_records = []
            raw_sample = []
            unique_materials = set()

            with open(path, "r", encoding="utf-8-sig", errors="replace") as fin:
                for rec, raw in processor.stream_filter(fin, keywords=keywords):
                    filtered_records.append(rec)
                    unique_materials.add(rec.name_de)
                    if len(raw_sample) < 50:  # Voransicht für Tabelle
                        raw_sample.append({
                            "Name_de": rec.name_de,
                            "Modul": rec.modul,
                            "GWPtotal_A2": _format_german_float(rec.gwp_total_a2),
                            "GWP_A1": _format_german_float(rec.gwp_a1_a2),
                            "Rohdichte_kg_m3": _format_german_float(rec.rohdichte_kg_m3),
                            "Bezugsgroesse": _format_german_float(rec.bezugsgroesse),
                            "Bezugseinheit": rec.bezugseinheit,
                            "UUID": rec.uuid,
                        })

            aggregation = processor.aggregate_materials_by_module(
                records=filtered_records,
                target_modules=modules,
                max_deviation_percent=tolerance
            )

            aggregation_table = []
            for mod in modules:
                d = aggregation.get(mod, {})
                aggregation_table.append({
                    "module": mod,
                    "mean_gwp": d.get("mean_gwp"),
                    "unit": d.get("unit", "kg"),
                    "within_tolerance": d.get("within_tolerance", False),
                    "deviation_percent": d.get("deviation_percent", 0.0),
                    "count": d.get("count", 0),
                    "min_gwp": d.get("min_gwp"),
                    "max_gwp": d.get("max_gwp"),
                    "status": d.get("status", ""),
                    "material_names": d.get("material_names", []),
                })

            return jsonify(
                filename=uploaded.filename,
                keywords=", ".join(keywords),
                count=len(filtered_records),
                unique_materials=len(unique_materials),
                tolerance=tolerance,
                aggregation=aggregation,
                aggregation_table=aggregation_table,
                raw_sample=raw_sample,
            )
    except Exception as error:
        return jsonify(error=f"Ökobaudat konnte nicht verarbeitet werden: {error}"), 422


@app.post("/api/obd-export-csv")
def obd_export_csv() -> Any:
    """Exportiert entweder die vermittelte Summary-CSV oder die gefilterte Roh-CSV."""
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Keine Datei erhalten."), 400

    keywords_raw = request.form.get("keywords", "")
    tolerance_raw = request.form.get("tolerance", "15.0")
    modules_raw = request.form.get("modules", "A1-A3, A4, A5")
    export_type = request.form.get("export_type", "summary")

    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    try:
        tolerance = float(tolerance_raw)
    except ValueError:
        tolerance = 15.0
    modules = [m.strip().upper() for m in modules_raw.split(",") if m.strip()]

    try:
        processor = OekobaudatProcessor(delimiter=";")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / Path(uploaded.filename).name
            uploaded.save(path)

            filtered_records = []
            raw_rows = []
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fin:
                for rec, raw in processor.stream_filter(fin, keywords=keywords):
                    filtered_records.append(rec)
                    if export_type == "filtered":
                        raw_rows.append(raw)

            buffer = io.StringIO()
            if export_type == "summary":
                aggregation = processor.aggregate_materials_by_module(
                    records=filtered_records,
                    target_modules=modules,
                    max_deviation_percent=tolerance
                )
                summary_fields = [
                    "Suchbegriffe", "Modul", "GWP_Vermittelt", "Einheit", "Innerhalb_15_Prozent",
                    "Abweichung_Prozent", "Anzahl_Datensaetze", "GWP_Min", "GWP_Max", "Status", "Beruecksichtigte_Baustoffe"
                ]
                writer = csv.DictWriter(buffer, fieldnames=summary_fields, delimiter=";")
                writer.writeheader()
                for mod in modules:
                    data = aggregation.get(mod, {})
                    writer.writerow({
                        "Suchbegriffe": ", ".join(keywords),
                        "Modul": mod,
                        "GWP_Vermittelt": _format_german_float(data.get("mean_gwp")) if data.get("mean_gwp") is not None else "",
                        "Einheit": data.get("unit", "kg"),
                        "Innerhalb_15_Prozent": "Ja" if data.get("within_tolerance") else "Nein",
                        "Abweichung_Prozent": _format_german_float(data.get("deviation_percent"), 1),
                        "Anzahl_Datensaetze": data.get("count", 0),
                        "GWP_Min": _format_german_float(data.get("min_gwp")) if data.get("min_gwp") is not None else "",
                        "GWP_Max": _format_german_float(data.get("max_gwp")) if data.get("max_gwp") is not None else "",
                        "Status": data.get("status", ""),
                        "Beruecksichtigte_Baustoffe": "; ".join(data.get("material_names", []))
                    })
                filename_out = f"oekobaudat_gwp_summary.csv"
            else:
                if raw_rows:
                    writer = csv.DictWriter(buffer, fieldnames=list(raw_rows[0].keys()), delimiter=";")
                    writer.writeheader()
                    writer.writerows(raw_rows)
                filename_out = f"oekobaudat_gefiltert.csv"

            byte_buf = io.BytesIO()
            byte_buf.write(buffer.getvalue().encode("utf-8-sig"))
            byte_buf.seek(0)

            return send_file(
                byte_buf,
                mimetype="text/csv",
                as_attachment=True,
                download_name=filename_out
            )
    except Exception as error:
        return jsonify(error=f"Export fehlgeschlagen: {error}"), 422


@app.post("/api/extract")
def extract() -> Any:
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Keine IFC-Datei erhalten."), 400
    if not uploaded.filename.lower().endswith(".ifc"):
        return jsonify(error="Bitte eine IFC-Datei hochladen."), 400

    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / Path(uploaded.filename).name
            uploaded.save(path)
            rows = _extract_rows(path)
        summary_rows = _build_material_summary(rows)

        return jsonify(
            filename=uploaded.filename,
            elements=len({row.get("Bauteil_GUID") or row.get("Element_GUID") for row in rows}),
            rows=len(rows),
            materials=len({row.get("Material_Name_IFC") or row.get("Material_Name") for row in rows}),
            rows_data=[{key: row.get(key, "") for key in CSV_EXPORT_COLUMNS} for row in rows],
            material_summary=summary_rows,
        )
    except Exception as error:
        return jsonify(error=f"IFC konnte nicht gelesen werden: {error}"), 422


@app.post("/api/export-csv")
def export_csv() -> Any:
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Keine IFC-Datei erhalten."), 400
    if not uploaded.filename.lower().endswith(".ifc"):
        return jsonify(error="Bitte eine IFC-Datei hochladen."), 400

    export_type = request.form.get("export_type", "detail")

    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / Path(uploaded.filename).name
            uploaded.save(path)
            rows = _extract_rows(path)

        exporter = CSVExporter()
        filename_stem = Path(uploaded.filename).stem

        if export_type == "summary":
            summary_rows = _build_material_summary(rows)
            exporter.data = summary_rows
            csv_content = exporter.to_csv_string(columns=CSV_MATERIAL_SUMMARY_COLUMNS)
            download_name = f"{filename_stem}_material_summary.csv"
        else:
            exporter.data = rows
            csv_content = exporter.to_csv_string(columns=CSV_EXPORT_COLUMNS)
            download_name = f"{filename_stem}_lca_extraction.csv"

        buffer = io.BytesIO()
        buffer.write(csv_content.encode("utf-8-sig"))
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype="text/csv",
            as_attachment=True,
            download_name=download_name,
        )
    except Exception as error:
        return jsonify(error=f"CSV-Export fehlgeschlagen: {error}"), 422


def main() -> None:
    app.run(host="127.0.0.1", port=5001, debug=True)


if __name__ == "__main__":
    main()