/**
 * Audio routing page: device list + connection controls for USB audio.
 * Shown on the Routing tab when operating_mode === 'audio' (the modes are
 * mutually exclusive — the MIDI matrix is not rendered in audio mode).
 *
 * Channel routing: once source and destination are picked, every REAL JACK
 * port (from jack_lsp, exposed via /api/audio/devices) appears as a
 * checkbox on its side. Checked outputs are paired positionally with
 * checked inputs and sent to the backend as an explicit full-port-name
 * mapping — no synthesised names involved anywhere.
 */

import { useState, useEffect, useCallback } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';

/** Channel label for a full "client:port" jack name → "Ch N". */
function chLabel(fullName) {
    const m = fullName.match(/(\d+)\s*$/);
    return m ? `Ch ${m[1]}` : fullName;
}

function portsFor(devices, deviceId, direction) {
    const dev = devices.find(d => d.device_id === deviceId);
    if (!dev || !Array.isArray(dev.ports)) return [];
    return dev.ports
        .filter(p => p.direction === direction && p.type !== 'midi')
        .map(p => p.name)
        .sort();
}

function toggleSet(set, value) {
    const next = Object.assign({}, set);
    if (next[value]) delete next[value];
    else next[value] = true;
    return next;
}

export function AudioRouting({ showToast }) {
    const [devices, setDevices] = useState([]);
    const [connections, setConnections] = useState([]);
    const [selectedSource, setSelectedSource] = useState('');
    const [selectedDest, setSelectedDest] = useState('');
    // Selected FULL port names per side (object used as a set)
    const [srcSel, setSrcSel] = useState({});
    const [dstSel, setDstSel] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const loadAudioData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const devs = await api('/audio/devices');
            if (devs.error) throw new Error(devs.error);
            setDevices(Array.isArray(devs) ? devs : []);

            const conns = await api('/audio/connections');
            if (conns.error) throw new Error(conns.error);
            setConnections(Array.isArray(conns) ? conns : []);
        } catch (err) {
            setError(err.message || 'Failed to load audio data');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadAudioData(); }, [loadAudioData]);

    // Which JACK ports each side offers, from live discovery data.
    const srcPorts = portsFor(devices, selectedSource, 'output');
    const dstPorts = portsFor(devices, selectedDest, 'input');

    function selectSource(id) {
        setSelectedSource(id);
        setSrcSel({});
    }

    function selectDest(id) {
        setSelectedDest(id);
        setDstSel({});
    }

    async function createConnection() {
        if (!selectedSource || !selectedDest) return;
        const outs = srcPorts.filter(p => srcSel[p]).sort();
        const ins = dstPorts.filter(p => dstSel[p]).sort();
        if (!outs.length || !ins.length) return;

        // Positional pairing, same ordering rule the engine's auto path
        // uses; extra channels on either side are simply not wired.
        const n = Math.min(outs.length, ins.length);
        const mapping = {};
        for (let i = 0; i < n; i++) mapping[outs[i]] = ins[i];

        try {
            const res = await api('/audio/connections', {
                method: 'POST',
                body: JSON.stringify({
                    source_device: selectedSource,
                    dest_device: selectedDest,
                    channel_mapping: mapping,
                }),
            });
            if (res.error) throw new Error(res.error);
            showToast && showToast(
                outs.length !== ins.length
                    ? `Connected ${n} ch (${outs.length} out vs ${ins.length} in)`
                    : `Connected ${n} ch`);
            setSelectedSource('');
            setSelectedDest('');
            setSrcSel({});
            setDstSel({});
            await loadAudioData();
        } catch (err) {
            setError(err.message || 'Failed to create connection');
        }
    }

    async function deleteConnection(id) {
        try {
            const res = await api(`/audio/connections/${id}`, { method: 'DELETE' });
            if (res.error) throw new Error(res.error);
            showToast && showToast('Connection removed');
            await loadAudioData();
        } catch (err) {
            setError(err.message || 'Failed to delete connection');
        }
    }

    const inputDevices = devices.filter(d => d.has_capture);
    const outputDevices = devices.filter(d => d.has_playback);
    const readyCount = Math.min(
        srcPorts.filter(p => srcSel[p]).length,
        dstPorts.filter(p => dstSel[p]).length);

    function devName(id) {
        const d = devices.find(x => x.device_id === id);
        return d ? d.name : id;
    }

    const portBoxStyle = {
        border: '1px solid var(--border)',
        borderRadius: '8px',
        padding: '0.5rem',
        maxHeight: '9rem',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.25rem',
    };

    function PortPicker({ title, ports, sel, onChange }) {
        return html`
            <div class="form-group">
                <label>${title} (${ports.filter(p => sel[p]).length}/${ports.length})</label>
                <div style=${portBoxStyle}>
                    ${ports.map(p => html`
                        <label key=${p} style="display:flex;align-items:center;gap:0.4rem">
                            <input type="checkbox" checked=${!!sel[p]}
                                   onchange=${() => onChange(toggleSet(sel, p))} />
                            <span>${chLabel(p)}</span>
                        </label>`)}
                    ${ports.length === 0 && html`<span class="muted">No ports online</span>`}
                </div>
            </div>`;
    }

    return html`
        <div class="audio-routing">
            ${error ? html`<div class="banner">${error}</div>` : ''}
            ${loading ? html`<div class="card"><p>Loading audio devices…</p></div>` : ''}

            <div class="card">
                <h3>New connection</h3>
                ${inputDevices.length === 0
                    ? html`<p>No input-capable audio devices found.</p>`
                    : html`
                        <div class="form-group">
                            <label for="aud-src">Source (capture)</label>
                            <select id="aud-src" value=${selectedSource}
                                    onchange=${e => selectSource(e.target.value)}>
                                <option value="">— select input —</option>
                                ${inputDevices.map(d => html`<option value=${d.device_id}>${d.name}</option>`)}
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="aud-dst">Destination (playback)</label>
                            <select id="aud-dst" value=${selectedDest}
                                    onchange=${e => selectDest(e.target.value)}>
                                <option value="">— select output —</option>
                                ${outputDevices.map(d => html`<option value=${d.device_id}>${d.name}</option>`)}
                            </select>
                        </div>
                        ${(srcPorts.length > 0 && dstPorts.length > 0) ? html`
                            <div style="display:flex;gap:0.75rem">
                                <${PortPicker} title="Source out" ports=${srcPorts}
                                               sel=${srcSel} onChange=${setSrcSel} />
                                <${PortPicker} title="Destination in" ports=${dstPorts}
                                               sel=${dstSel} onChange=${setDstSel} />
                            </div>` : null}
                        <button class="btn btn-primary"
                                disabled=${!selectedSource || !selectedDest || !readyCount}
                                onclick=${createConnection}>
                            Connect${readyCount ? ` ${readyCount} ch` : ''}
                        </button>
                    `}
            </div>

            <div class="card">
                <h3>Connections (${connections.length})</h3>
                ${connections.length === 0
                    ? html`<p>No audio connections yet.</p>`
                    : connections.map(c => html`
                        <div class="aud-row">
                            <span class="aud-path">
                                ${devName(c.source_device)} → ${devName(c.dest_device)}
                                · ${Object.keys(c.channel_mapping || {}).length}ch
                            </span>
                            <button class="btn btn-danger"
                                    onclick=${() => deleteConnection(c.id)}>Delete</button>
                        </div>
                    `)}
            </div>

            <div class="card">
                <h3>Devices (${devices.length})</h3>
                ${devices.map(d => html`
                    <div class="aud-row">
                        <span>${d.name}</span>
                        <span class="aud-caps">
                            ${[d.has_capture && 'in', d.has_playback && 'out'].filter(Boolean).join(' / ') || '—'}
                            · ${d.channels?.input_count || 0}ch in · ${d.channels?.output_count || 0}ch out
                        </span>
                    </div>
                `)}
            </div>
        </div>`;
}
