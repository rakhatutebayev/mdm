'use client';

import { useEffect, useRef, useCallback } from 'react';
import styles from './PtyTerminal.module.css';

interface PtyTerminalProps {
  deviceId: string;
  token: string;
}

export default function PtyTerminal({ deviceId, token }: PtyTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<import('@xterm/xterm').Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<import('@xterm/addon-fit').FitAddon | null>(null);

  const connect = useCallback(() => {
    if (!containerRef.current) return;

    // Lazy-load xterm (client-only)
    import('@xterm/xterm').then(({ Terminal }) => {
      import('@xterm/addon-fit').then(({ FitAddon }) => {
        import('@xterm/addon-web-links').then(({ WebLinksAddon }) => {
          // Dispose previous instance
          if (termRef.current) {
            termRef.current.dispose();
          }
          if (wsRef.current) {
            wsRef.current.close();
          }

          const term = new Terminal({
            cursorBlink: true,
            fontSize: 13,
            fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
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

          // Build WebSocket URL
          const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          const host = window.location.host;
          // Connect to backend directly (API proxy)
          const wsUrl = `${proto}//${host}/api/mdm/ws/terminal/${deviceId}?t=${encodeURIComponent(token)}`;

          term.writeln('\x1b[1;32mConnecting to remote terminal...\x1b[0m');

          const ws = new WebSocket(wsUrl);
          ws.binaryType = 'arraybuffer';
          wsRef.current = ws;

          ws.onopen = () => {
            term.writeln('\x1b[1;32mConnected.\x1b[0m\r\n');
          };

          ws.onmessage = (evt) => {
            if (evt.data instanceof ArrayBuffer) {
              term.write(new Uint8Array(evt.data));
            } else if (typeof evt.data === 'string') {
              try {
                const msg = JSON.parse(evt.data);
                if (msg.type === 'error') {
                  term.writeln(`\r\n\x1b[1;31mError: ${msg.message}\x1b[0m`);
                }
              } catch {
                term.write(evt.data);
              }
            }
          };

          ws.onclose = (evt) => {
            term.writeln(`\r\n\x1b[1;33mConnection closed (${evt.code}).\x1b[0m`);
          };

          ws.onerror = () => {
            term.writeln('\r\n\x1b[1;31mWebSocket error.\x1b[0m');
          };

          // Send keystrokes to agent via WebSocket
          term.onData((data) => {
            if (ws.readyState === WebSocket.OPEN) {
              const encoded = new TextEncoder().encode(data);
              ws.send(encoded);
            }
          });

          // Send terminal resize events
          term.onResize(({ cols, rows }) => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'resize', cols, rows }));
            }
          });
        });
      });
    });
  }, [deviceId, token]);

  useEffect(() => {
    connect();

    const handleResize = () => {
      fitRef.current?.fit();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      wsRef.current?.close();
      termRef.current?.dispose();
    };
  }, [connect]);

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>⚡ Remote Terminal</span>
        <button
          className={styles.reconnectBtn}
          onClick={connect}
          title="Reconnect"
        >
          ↺ Reconnect
        </button>
      </div>
      <div ref={containerRef} className={styles.terminal} />
    </div>
  );
}
