'use client';

import React, { useEffect, useRef, useCallback, useState } from 'react';
import styles from './PtyTerminal.module.css';

interface PtyTerminalProps {
  deviceId: string;
  token: string;
}

interface ContextMenu {
  x: number;
  y: number;
}

export default function PtyTerminal({ deviceId, token }: PtyTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<import('@xterm/xterm').Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<import('@xterm/addon-fit').FitAddon | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);

  const connect = useCallback(() => {
    if (!containerRef.current) return;

    import('@xterm/xterm').then(({ Terminal }) => {
      import('@xterm/addon-fit').then(({ FitAddon }) => {
        import('@xterm/addon-web-links').then(({ WebLinksAddon }) => {
          if (termRef.current) termRef.current.dispose();
          if (wsRef.current) wsRef.current.close();

          const term = new Terminal({
            cursorBlink: true,
            fontSize: 13,
            fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
            scrollOnUserInput: true,
            rightClickSelectsWord: true,
            macOptionIsMeta: true,
            theme: {
              background: '#0f0f17',
              foreground: '#d4d4d4',
              cursor: '#00ff88',
              selectionBackground: '#264f78',
              black: '#1e1e2e',
              red: '#f38ba8',
              green: '#a6e3a1',
              yellow: '#f9e2af',
              blue: '#89b4fa',
              magenta: '#cba6f7',
              cyan: '#89dceb',
              white: '#cdd6f4',
              brightBlack: '#585b70',
              brightRed: '#f38ba8',
              brightGreen: '#a6e3a1',
              brightYellow: '#f9e2af',
              brightBlue: '#89b4fa',
              brightMagenta: '#cba6f7',
              brightCyan: '#89dceb',
              brightWhite: '#cdd6f4',
            },
            allowProposedApi: true,
          });

          const fitAddon = new FitAddon();
          term.loadAddon(fitAddon);
          term.loadAddon(new WebLinksAddon());
          term.open(containerRef.current!);
          fitAddon.fit();

          termRef.current = term;
          fitRef.current = fitAddon;

          const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          const wsUrl = `${proto}//${window.location.host}/ws/terminal/${deviceId}?t=${encodeURIComponent(token)}`;

          term.writeln('\x1b[1;32mConnecting to remote terminal...\x1b[0m');

          const ws = new WebSocket(wsUrl);
          ws.binaryType = 'arraybuffer';
          wsRef.current = ws;

          ws.onopen = () => term.writeln('\x1b[1;32mConnected.\x1b[0m\r\n');

          ws.onmessage = (evt) => {
            if (evt.data instanceof ArrayBuffer) {
              term.write(new Uint8Array(evt.data));
            } else if (typeof evt.data === 'string') {
              try {
                const msg = JSON.parse(evt.data);
                if (msg.type === 'error') term.writeln(`\r\n\x1b[1;31mError: ${msg.message}\x1b[0m`);
              } catch { term.write(evt.data); }
            }
          };

          ws.onclose = (evt) => term.writeln(`\r\n\x1b[1;33mConnection closed (${evt.code}).\x1b[0m`);
          ws.onerror = () => term.writeln('\r\n\x1b[1;31mWebSocket error.\x1b[0m');

          // Ctrl+C → copy if text selected, otherwise send SIGINT
          // Ctrl+V → paste from clipboard
          term.attachCustomKeyEventHandler((e: KeyboardEvent) => {
            if (e.ctrlKey && e.key === 'c' && !e.shiftKey) {
              const sel = term.getSelection();
              if (sel) {
                navigator.clipboard.writeText(sel).catch(() => {});
                return false; // prevent sending to PTY
              }
            }
            if (e.ctrlKey && e.key === 'v' && !e.shiftKey && e.type === 'keydown') {
              navigator.clipboard.readText().then(text => {
                if (text && ws.readyState === WebSocket.OPEN) {
                  ws.send(new TextEncoder().encode(text));
                }
              }).catch(() => {});
              return false; // prevent default
            }
            return true;
          });

          term.onData((data) => {
            if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
          });

          term.onResize(({ cols, rows }) => {
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows }));
          });
        });
      });
    });
  }, [deviceId, token]);

  // Copy selected text from terminal
  const handleCopy = useCallback(() => {
    const term = termRef.current;
    if (!term) return;
    const selection = term.getSelection();
    if (selection) navigator.clipboard.writeText(selection).catch(() => {});
    setContextMenu(null);
    term.focus();
  }, []);

  // Paste from clipboard into terminal
  const handlePaste = useCallback(async () => {
    setContextMenu(null);
    const term = termRef.current;
    const ws = wsRef.current;
    if (!term || !ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      const text = await navigator.clipboard.readText();
      if (text) ws.send(new TextEncoder().encode(text));
    } catch {
      // clipboard permission denied — try execCommand fallback
    }
    term.focus();
  }, []);

  // Select all text visible in terminal
  const handleSelectAll = useCallback(() => {
    termRef.current?.selectAll();
    setContextMenu(null);
    termRef.current?.focus();
  }, []);

  const handleClearSelection = useCallback(() => {
    termRef.current?.clearSelection();
    setContextMenu(null);
    termRef.current?.focus();
  }, []);

  useEffect(() => {
    connect();
    const handleResize = () => fitRef.current?.fit();
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      wsRef.current?.close();
      termRef.current?.dispose();
    };
  }, [connect]);

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('keydown', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('keydown', close);
    };
  }, [contextMenu]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    setContextMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, []);

  const hasSelection = termRef.current ? termRef.current.getSelection().length > 0 : false;

  return (
    <div ref={wrapperRef} className={styles.wrapper} onContextMenu={handleContextMenu}>
      <div className={styles.header}>
        <span className={styles.title}>⚡ Remote Terminal</span>
        <button className={styles.reconnectBtn} onClick={connect} title="Reconnect">
          ↺ Reconnect
        </button>
      </div>
      <div ref={containerRef} className={styles.terminal} />

      {contextMenu && (
        <div
          className={styles.contextMenu}
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={e => e.stopPropagation()}
        >
          <button className={styles.menuItem} onClick={handleCopy} disabled={!hasSelection}>
            <span className={styles.menuIcon}>⎘</span> Copy
            <span className={styles.menuShortcut}>Ctrl+C</span>
          </button>
          <button className={styles.menuItem} onClick={handlePaste}>
            <span className={styles.menuIcon}>📋</span> Paste
            <span className={styles.menuShortcut}>Ctrl+V</span>
          </button>
          <div className={styles.menuDivider} />
          <button className={styles.menuItem} onClick={handleSelectAll}>
            <span className={styles.menuIcon}>▣</span> Select All
          </button>
          <button className={styles.menuItem} onClick={handleClearSelection}>
            <span className={styles.menuIcon}>✕</span> Clear Selection
          </button>
        </div>
      )}
    </div>
  );
}
