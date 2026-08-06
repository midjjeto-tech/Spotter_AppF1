import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono, Oswald, Titillium_Web } from 'next/font/google'
import './globals.css'

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] })
const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})
const oswald = Oswald({
  variable: '--font-oswald',
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
})
// Шрифт игрового оверлея. Курсив обязателен: на нём держится весь наклонный
// язык трансляции (заголовки панелей, коды пилотов), а у Oswald начертания
// italic нет вовсе — подмена дала бы faux-italic.
//
// Кириллицы у Titillium нет, поэтому им НЕ набирается русский текст оверлея
// (имена говорящих, советы инженера) — он остаётся на --font-sans.
const titillium = Titillium_Web({
  variable: '--font-titillium',
  subsets: ['latin'],
  weight: ['400', '600', '700', '900'],
  style: ['normal', 'italic'],
})

export const metadata: Metadata = {
  title: 'Spotter App — AI Race Engineer',
  description:
    'AI спортивный комментатор и инженер для F1 25 и других симуляторов. UDP-телеметрия, живые позиции и озвучка в реальном времени.',
  generator: 'v0.app',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#0a0a0c',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="ru"
      className={`dark ${geistSans.variable} ${geistMono.variable} ${oswald.variable} ${titillium.variable} bg-background`}
    >
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
