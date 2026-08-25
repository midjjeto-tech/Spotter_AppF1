/** @type {import('next').NextConfig} */
const nextConfig = {
  // Статический экспорт: Next собирает в out/ (HTML+JS+CSS), который отдаёт web_server.py
  // вместо старого index.html. Рантайм Node конечному пользователю не нужен.
  output: 'export',
  images: {
    unoptimized: true,
  },
}

export default nextConfig
