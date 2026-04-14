// start.js - 放在 D:\dragon-board 目录
import { spawn } from 'child_process'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import fs from 'fs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

console.log('='.repeat(60))
console.log('🚀 启动股票数据代理服务器和前端')
console.log('='.repeat(60))

// 检查 server.js 是否存在
const serverPath = join(__dirname, 'server.js')
if (!fs.existsSync(serverPath)) {
  console.error('❌ 错误: 找不到 server.js')
  console.error(`   期望路径: ${serverPath}`)
  process.exit(1)
}

console.log('📡 [1/2] 启动代理服务器...')
// 启动代理服务器（直接在当前目录运行 server.js）
const proxy = spawn('cmd', ['/c', 'start "代理服务器" cmd /k "node server.js"'], {
  shell: true,
  detached: true,
  stdio: 'ignore',
})
proxy.unref()

console.log('⏳ 等待服务器启动...')
setTimeout(() => {
  console.log('💻 [2/2] 启动前端...')
  // 检查前端是否在 dragon-board 目录（Vue 项目）
  const frontendPath = join(__dirname, 'package.json')
  if (fs.existsSync(frontendPath)) {
    // 如果在当前目录有 package.json，说明前端也在同一个目录
    const frontend = spawn('cmd', ['/c', 'start "前端" cmd /k "npm run dev"'], {
      shell: true,
      detached: true,
      stdio: 'ignore',
    })
    frontend.unref()
  } else {
    console.log('⚠️ 未找到前端项目，请手动启动前端')
    console.log('   如果前端在其他目录，请修改启动脚本')
  }

  console.log('✅ 启动完成！')
  console.log('   代理服务器: http://localhost:3000')
  console.log('   测试页面: http://localhost:3000/test.html')
  console.log('='.repeat(60))
}, 3000)
