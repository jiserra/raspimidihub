/**
 * Audio routing page: device list + connection controls for USB audio.
 * Shown on the Routing tab when operating_mode === 'audio' (the modes are
 * mutually exclusive — the MIDI matrix is not rendered in audio mode).
 */

import { useState, useEffect, useCallback } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';

export function AudioRouting({ showToast }) {
    const [devices, setDevices] = useState([]);
    const [connections, setConnections] = useState([]);
    const [selectedSource, setSelectedSource] = useState('');
    const [selectedDest, setSelectedDest] = useState('');
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

    async function createConnection() {
        if (!selectedSource || !selectedDest) return;
        try {
            const res = await api('/audio/connections', {
                method: 'POST',
                body: JSON.stringify({
                    source_device: selectedSource,
                    dest_device: selectedDest,
                    channel_mapping: {},
                }),
            });
            if (res.error) throw new Error(res.error);
            showToast && showToast('Audio connection created');
            setSelectedSource('');
            setSelectedDest('');
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

    function devName(id) {
        const d = devices.find(x => x.device_id === id);
        return d ? d.name : id;
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
                                    onchange=${e => setSelectedSource(e.target.value)}>
                                <option value="">— select input —</option>
                                ${inputDevices.map(d => html`<option value=${d.device_id}>${d.name}</option>`)}
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="aud-dst">Destination (playback)</label>
                            <select id="aud-dst" value=${selectedDest}
                                    onchange=${e => setSelectedDest(e.target.value)}>
                                <option value="">— select output —</option>
                                ${outputDevices.map(d => html`<option value=${d.device_id}>${d.name}</option>`)}
                            </select>
                        </div>
                        <button class="btn btn-primary"
                                disabled=${!selectedSource || !selectedDest}
                                onclick=${createConnection}>
                            Connect
                        </button>
                    `}
            </div>

            <div class="card">
                <h3>Connections (${connections.length})</h3>
                ${connections.length === 0
                    ? html`<p>No audio connections yet.</p>`
                    : connections.map(c => html`
                        <div class="aud-row">
                            <span class="aud-path">${devName(c.source_device)} → ${devName(c.dest_device)}</span>
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
