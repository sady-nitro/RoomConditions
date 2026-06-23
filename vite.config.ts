import { defineConfig, type Plugin } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { execFile } from 'node:child_process'

const BME280_SCRIPT =
  process.env.BME280_SCRIPT ??
  '/home/sadynitro/workspace/source/locals/python/ss/bme280.py'
const PYTHON_COMMAND = process.env.PYTHON_COMMAND ?? 'python'

function getLatestMeasurementRow(source: string) {
  const rows = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const columns = rows[index].split(',').map((value) => value.trim())
    if (columns.length !== 5) continue

    const [date, hourText, temperatureText, humidityText, pressureText] =
      columns
    const hour = Number(hourText)
    const values = [
      Number(temperatureText),
      Number(humidityText),
      Number(pressureText),
    ]

    if (
      /^\d{4}-\d{2}-\d{2}$/.test(date) &&
      Number.isInteger(hour) &&
      hour >= 0 &&
      hour <= 23 &&
      values.every(Number.isFinite)
    ) {
      return columns.join(',')
    }
  }

  throw new Error(
    `bme280.py did not output a valid data.csv row: ${source.trim() || '(empty)'}`,
  )
}

function currentMeasurementApi(): Plugin {
  return {
    name: 'current-measurement-api',
    configureServer(server) {
      server.middlewares.use('/api/current-measurement', (request, response) => {
        if (request.method !== 'GET') {
          response.statusCode = 405
          response.setHeader('Allow', 'GET')
          response.end('Method Not Allowed')
          return
        }

        execFile(
          PYTHON_COMMAND,
          [BME280_SCRIPT],
          {
            encoding: 'utf8',
            timeout: 15_000,
            windowsHide: true,
          },
          (error, stdout, stderr) => {
            response.setHeader('Cache-Control', 'no-store')

            if (error) {
              console.error('Failed to execute bme280.py:', error)
              if (stderr.trim()) console.error(stderr.trim())
              response.statusCode = 500
              response.end('Failed to read the BME280 sensor')
              return
            }

            try {
              const measurementRow = getLatestMeasurementRow(stdout)
              response.statusCode = 200
              response.setHeader('Content-Type', 'text/csv; charset=utf-8')
              response.end(`${measurementRow}\n`)
            } catch (parseError) {
              console.error(parseError)
              response.statusCode = 500
              response.end('Invalid output from bme280.py')
            }
          },
        )
      })
    },
  }
}

function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

export default defineConfig({
  plugins: [
    figmaAssetResolver(),
    currentMeasurementApi(),
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],
})
