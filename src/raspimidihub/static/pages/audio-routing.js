/**
 * Audio routing page (operating_mode === 'audio').
 *
 * Reuses the EXACT same routing surfaces as MIDI mode — ConnectionMatrix
 * and RackView — fed with matrix-shaped data from /api/audio/devices and
 * /api/audio/connections. Each matrix cell is one real JACK wire
 * (source output channel → destination input channel); tap a cell for
 * Add/Remove. Devices appear as rows/columns of their live JACK ports
 * ("Ch N"). Filters/mappings/plugins/Bluetooth are MIDI concepts and
 * deliberately absent here; Save/Load Config persist the audio graph
 * through the normal config pipeline.
 */

import { useState, useEffect, useCallback } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';
import { ConnectionMatrix } from './matrix.js';
import { RackView } from './rack.js';
import { cableColor } from '../ui/connections.js';

// Same key the MIDI routing page uses — one display preference across
// both modes.
const VIEW_KEY = 'raspimidihub:routingView';
function loadView() { try { return localStorage.getItem(VIEW_KEY) === 'rack' ? 'rack' : 'matrix'; } catch { return 'matrix'; } }
function saveView(v) { try { localStorage.setItem(VIEW_KEY, v); } catch {} }

export function AudioRouting({ showToast, showContextMenu }) {
    const [devices, setDevices] = useState([]);
    const [connections, setConnections] = useState([]);
    const [view, setViewState] = useState(loadView());
    const setView = (v) => { setViewState(v); saveView(v); };

    const refresh = useCallback(async () => {
        try {
            const [devs, conns] = await Promise.all([
                fetch('/api/audio/devices').then(r => r.json()),
                fetch('/api/audio/connections').then(r => r.json()),
            ]);
            setDevices(Array.isArray(devs) ? devs : []);
            setConnections(Array.isArray(conns) ? conns : []);
        } catch (e) {
            console.warn('audio routing refresh failed:', e);
        }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    // Server pushes after every create/delete/hotplug — mirror the MIDI
    // page's lifecycle (App-level refresh targets the MIDI endpoints,
    // which answer [] in audio mode, so this page listens directly).
    useEffect(() => {
        const es = new EventSource('/api/events');
        const h = () => refresh();
        es.addEventListener('connection-changed', h);
        es.addEventListener('device-connected', h);
        es.addEventListener('device-disconnected', h);
        es.addEventListener('config-dirty', h);
        return () => es.close();
    }, [refresh]);

    const onToggle = async (inp, out, connect) => {
        if (connect) {
            await apiPost('/api/audio/connections', {
                src_client: inp.client_id, src_port: inp.port_id,
                dst_client: out.client_id, dst_port: out.port_id,
            });
        } else {
            const conn = connections.find(c =>
                c.src_client === inp.client_id && c.src_port === inp.port_id
                && c.dst_client === out.client_id && c.dst_port === out.port_id);
            if (!conn) return;
            await fetch(`/api/audio/connections/${encodeURIComponent(conn.id)}`,
                { method: 'DELETE' });
        }
        refresh();
    };

    const endpointLabel = (item, role) =>
        `${item.dev_name || '?'} · ${role === 'out' ? 'OUT' : 'IN'}`;

    const cellMenuItems = (inp, out, conn) => {
        const header = {
            header: true,
            label: `${endpointLabel(inp, 'out')}  →  ${endpointLabel(out, 'in')}`,
            color: cableColor(inp.stable_id, inp.port_id),
        };
        if (conn) {
            return [
                header, { divider: true },
                { label: 'Remove', action: () => onToggle(inp, out, false), danger: true },
            ];
        }
        return [
            header, { divider: true },
            { label: 'Add connection', action: () => onToggle(inp, out, true) },
        ];
    };

    const headerMenuItems = (item /* , role, fullLabel */) => [
        { header: true, label: item.dev_name },
        { divider: true },
    ];

    const saveConfig = async () => {
        try {
            const res = await fetch('/api/config/save', { method: 'POST' })
                .then(r => r.json());
            showToast(res && res.status === 'saved'
                ? 'Configuration saved'
                : (res && res.error) || 'Save failed — try again');
        } catch {
            showToast('Save failed — try again');
        }
    };

    return html`
        <div class="view-toggle">
            <button class="view-toggle-btn ${view === 'matrix' ? 'active' : ''}"
                    onclick=${() => setView('matrix')}>Matrix</button>
            <button class="view-toggle-btn ${view === 'rack' ? 'active' : ''}"
                    onclick=${() => setView('rack')}>Rack</button>
        </div>
        ${view === 'rack'
            ? html`<${RackView} devices=${devices} connections=${connections}
                clockSources=${{}} clockQuarters=${null} midiRates=${null}
                onToggle=${onToggle}
                getCellMenuItems=${cellMenuItems}
                getHeaderMenuItems=${headerMenuItems}
                showContextMenu=${showContextMenu} />`
            : html`<${ConnectionMatrix} devices=${devices} connections=${connections}
                clockSources=${{}} clockQuarters=${null} midiRates=${null}
                onAddPlugin=${null}
                getCellMenuItems=${cellMenuItems}
                getHeaderMenuItems=${headerMenuItems}
                showContextMenu=${showContextMenu} />`}
        <div class="btn-group">
            <button class="btn btn-primary" onclick=${saveConfig}>Save Config</button>
        </div>
        <p style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:4px">
            Audio mode: each cell wires one source channel to one destination channel.
        </p>
    `;
}

async function apiPost(url, body) {
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return await r.json();
    } catch (e) {
        return { error: String(e) };
    }
}
