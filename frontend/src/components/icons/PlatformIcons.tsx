import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
  color?: string;
  style?: React.CSSProperties;
}

export function AppleIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 814 1000" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 680.4 0 588.4 0 500.5c0-225.6 147.2-344.8 292.3-344.8 74.9 0 137.2 49.3 184.5 49.3 44.9 0 115.7-52 201.5-52 32.4 0 108.2 2.6 168.8 75.3zm-126.7-175.6c-28.5 35.3-75.3 62.2-122.6 62.2-6.4 0-12.8-.6-19.2-1.9 1.3-43.5 22.4-88.2 51.3-116.7 32.4-31.7 87.5-55.9 133.5-58.5 1.3 7.7 1.9 15.4 1.9 22.4 0 41.5-16.6 85.5-44.9 92.5z"/>
    </svg>
  );
}

export function AndroidIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M6 18c0 .55.45 1 1 1h1v3.5c0 .83.67 1.5 1.5 1.5S11 23.33 11 22.5V19h2v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h1c.55 0 1-.45 1-1V8H6v10zM3.5 8C2.67 8 2 8.67 2 9.5v7c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-7C5 8.67 4.33 8 3.5 8zm17 0c-.83 0-1.5.67-1.5 1.5v7c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-7c0-.83-.67-1.5-1.5-1.5zm-4.97-5.84l1.3-1.3c.2-.2.2-.51 0-.71-.2-.2-.51-.2-.71 0l-1.48 1.48C13.85 1.23 12.95 1 12 1c-.96 0-1.86.23-2.66.63L7.85.15c-.2-.2-.51-.2-.71 0-.2.2-.2.51 0 .71l1.31 1.31C7.08 3.35 6 5.05 6 7h12c0-1.95-1.08-3.65-2.47-4.84zM10 5H9V4h1v1zm5 0h-1V4h1v1z"/>
    </svg>
  );
}

export function WindowsIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/>
    </svg>
  );
}

export function MacOSIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 814 1000" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 680.4 0 588.4 0 500.5c0-225.6 147.2-344.8 292.3-344.8 74.9 0 137.2 49.3 184.5 49.3 44.9 0 115.7-52 201.5-52 32.4 0 108.2 2.6 168.8 75.3zm-126.7-175.6c-28.5 35.3-75.3 62.2-122.6 62.2-6.4 0-12.8-.6-19.2-1.9 1.3-43.5 22.4-88.2 51.3-116.7 32.4-31.7 87.5-55.9 133.5-58.5 1.3 7.7 1.9 15.4 1.9 22.4 0 41.5-16.6 85.5-44.9 92.5z"/>
    </svg>
  );
}

export function IPadOSIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M18.5 0h-13C4.12 0 3 1.12 3 2.5v19C3 22.88 4.12 24 5.5 24h13c1.38 0 2.5-1.12 2.5-2.5v-19C21 1.12 19.88 0 18.5 0zm-6.5 23c-.83 0-1.5-.67-1.5-1.5S11.17 20 12 20s1.5.67 1.5 1.5S12.83 23 12 23zM19 18H5V3h14v15z"/>
    </svg>
  );
}

export function ChromeOSIcon({ size = 16, className, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} fill={color} xmlns="http://www.w3.org/2000/svg">
      <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm0 4a8 8 0 0 1 6.928 4H12a4 4 0 0 0-4 4H3.072A8 8 0 0 1 12 4zm0 16a8 8 0 0 1-6.928-4H8a4.002 4.002 0 0 0 7.745-1H20.928A8 8 0 0 1 12 20zm2-8a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm2.236 4H8.764A5.978 5.978 0 0 1 6 12c0-1.48.537-2.83 1.42-3.866L9.55 12h.002a2.5 2.5 0 0 0 4.897 0h.001l2.13-3.866A5.988 5.988 0 0 1 18 12a5.978 5.978 0 0 1-1.764 4z"/>
    </svg>
  );
}

/** Compact icon for use in tables/lists. Returns svg icon for a given platform string */
export function PlatformIcon({ platform, size = 15 }: { platform: string; size?: number }) {
  const style: React.CSSProperties = { flexShrink: 0 };
  switch (platform) {
    case 'iOS':     return <AppleIcon   size={size} style={style} />;
    case 'macOS':   return <MacOSIcon   size={size} style={style} />;
    case 'iPadOS':  return <IPadOSIcon  size={size} style={style} />;
    case 'Android': return <AndroidIcon size={size} style={style} />;
    case 'Windows': return <WindowsIcon size={size} style={style} />;
    case 'ChromeOS':return <ChromeOSIcon size={size} style={style} />;
    default:        return <span style={{ fontSize: size }}>{platform[0]}</span>;
  }
}
