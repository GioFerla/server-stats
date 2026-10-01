'use strict';
let energySample = null;
const energyPrice = document.getElementById('energy-price');
const energyWatts = document.getElementById('energy-watts');
const energyKey = 'server-stats.energy.v1';
let tariffLoaded = false;
let tariffDirty = false;
function validEnergyNumber(input) {
  if (input.value.trim() === '' || !input.validity.valid) return null;
  const value = Number(input.value);
  return Number.isFinite(value) && value >= 0 ? value : null;
}
try {
  const saved = JSON.parse(localStorage.getItem(energyKey));
  if (saved && Number.isFinite(saved.price) && saved.price >= 0) energyPrice.value = saved.price;
  if (saved && Number.isFinite(saved.watts) && saved.watts >= 0) energyWatts.value = saved.watts;
} catch (_) { /* Browser storage may be unavailable. */ }
function energyProjection(watts, price, hours) {
  const kwh = watts / 1000 * hours;
  return { kwh, cost: kwh * price };
}
function renderEnergy(sample) {
  energySample = sample;
  if (sample.energy) {
    if (!tariffLoaded || (!tariffDirty && document.activeElement !== energyPrice)) {
      energyPrice.value = sample.energy.price;
      tariffLoaded = true;
    }
    renderAccounting(sample.energy);
  }
  const price = validEnergyNumber(energyPrice);
  const manual = validEnergyNumber(energyWatts);
  const samples = (sample.history || []).filter(s => s.timestamp >= sample.timestamp - 60 && Number.isFinite(s.power_cpu));
  const measured = samples.length ? samples.reduce((sum, s) => sum + s.power_cpu, 0) / samples.length : null;
  const watts = manual === null ? measured : manual;
  const invalidManual = energyWatts.value.trim() !== '' && manual === null;
  const source = document.getElementById('energy-source');
  if (price === null || invalidManual) {
    source.textContent = 'Inserisci valori numerici maggiori o uguali a zero.';
  } else if (watts === null) {
    source.textContent = 'Misura CPU non disponibile: inserisci la potenza totale stimata in watt.';
  } else {
    const formatted = watts.toLocaleString('it-IT', { maximumFractionDigits: 2 });
    source.textContent = manual === null
      ? 'Stima della sola CPU · ' + formatted + ' W medi nell’ultimo minuto. Il consumo totale del server è superiore.'
      : 'Stima dell’intero server · potenza inserita: ' + formatted + ' W.';
  }
  for (const [period, hours] of [['hour', 1], ['day', 24], ['month', 720]]) {
    const value = watts !== null && price !== null && !invalidManual ? energyProjection(watts, price, hours) : null;
    document.getElementById('cost-' + period).textContent = value ? value.cost.toLocaleString('it-IT', { style: 'currency', currency: 'EUR', minimumFractionDigits: period === 'hour' ? 3 : 2, maximumFractionDigits: period === 'hour' ? 3 : 2 }) : '—';
    document.getElementById('kwh-' + period).textContent = value ? value.kwh.toLocaleString('it-IT', { maximumFractionDigits: 4 }) + ' kWh' : '—';
  }
}
for (const input of [energyPrice, energyWatts]) input.addEventListener('input', () => {
  if (input === energyPrice) {
    tariffDirty = true;
    document.getElementById('energy-save-status').textContent = 'Tariffa modificata: salva per applicarla ai nuovi consumi. I costi passati restano invariati.';
  }
  try { localStorage.setItem(energyKey, JSON.stringify({price:validEnergyNumber(energyPrice), watts:validEnergyNumber(energyWatts)})); } catch (_) {}
  if (energySample) renderEnergy(energySample);
});

function measuredMoney(value) {
  return value.toLocaleString('it-IT', {style:'currency', currency:'EUR', minimumFractionDigits:4, maximumFractionDigits:6});
}
function measuredKwh(value) {
  return value.toLocaleString('it-IT', {maximumFractionDigits:6}) + ' kWh';
}
function measuredDuration(seconds) {
  const s = Math.floor(seconds);
  return Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm ' + s % 60 + 's';
}
function renderAccounting(ledger) {
  for (const period of ['today','month','total']) {
    document.getElementById('actual-' + period).textContent = measuredMoney(ledger[period].cost);
    document.getElementById('actual-kwh-' + period).textContent = measuredKwh(ledger[period].kwh);
  }
  const date = new Date(ledger.started_at * 1000).toLocaleString('it-IT', {timeZone:ledger.timezone});
  const tariff = ledger.price.toLocaleString('it-IT', {maximumFractionDigits:6});
  document.getElementById('energy-accounting').textContent = 'Conteggio dal ' + date + ' · tariffa attiva ' + tariff + ' €/kWh · giorni e mesi in ' + ledger.timezone + '.';
  const total = ledger.total;
  const elapsed = total.measured_seconds + total.missing_seconds;
  const coverage = elapsed ? (100 * total.measured_seconds / elapsed).toLocaleString('it-IT', {maximumFractionDigits:2}) : '0';
  document.getElementById('energy-coverage').textContent = (ledger.measurement_available === false ? 'Misura CPU attualmente non disponibile. ' : '') + 'Tempo misurato: ' + measuredDuration(total.measured_seconds) + ' · copertura ' + coverage + '% · tempo senza misura: ' + measuredDuration(total.missing_seconds) + '.';
  const table = document.getElementById('energy-days');
  table.replaceChildren();
  for (const day of ledger.days) {
    const row = document.createElement('tr');
    for (const value of [new Date(day.day + 'T12:00:00Z').toLocaleDateString('it-IT'), measuredKwh(day.kwh), measuredMoney(day.cost), measuredDuration(day.measured_seconds), measuredDuration(day.missing_seconds)]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    }
    table.appendChild(row);
  }
}
document.getElementById('energy-save').addEventListener('click', async () => {
  const button = document.getElementById('energy-save');
  const message = document.getElementById('energy-save-status');
  const price = validEnergyNumber(energyPrice);
  if (price === null || price > 100) {
    message.textContent = 'Inserisci una tariffa tra 0 e 100 €/kWh.';
    return;
  }
  button.disabled = true;
  const savedPrice = price;
  try {
    const response = await fetch('/api/energy/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({price})});
    if (response.status === 401) { location.assign('/login'); return; }
    const ledger = await response.json();
    if (!response.ok) throw new Error(ledger.error || 'Salvataggio non riuscito.');
    if (validEnergyNumber(energyPrice) === savedPrice) {
      tariffDirty = false;
      message.textContent = 'Tariffa salvata sul server. I costi già maturati restano invariati.';
    } else {
      message.textContent = 'Salvata la tariffa precedente; salva di nuovo le modifiche attuali.';
    }
    if (energySample) renderEnergy({...energySample, energy:{...ledger, measurement_available:energySample.energy?.measurement_available}});
  } catch (error) { message.textContent = error.message || 'Connessione non disponibile. Riprova.'; }
  finally { button.disabled = false; }
});
