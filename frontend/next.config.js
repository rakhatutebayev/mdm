/** @type {import('next').NextConfig} */
const nextConfig = {
    async rewrites() {
        // API_URL is a server-only variable used for Docker internal networking.
        // Falls back to NEXT_PUBLIC_API_URL (browser-facing) then to localhost for local dev.
        const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        return [
            {
                source: '/api/v1/:path*',
                destination: `${apiUrl}/api/v1/:path*`,
            },
        ];
    },
};

module.exports = nextConfig;
