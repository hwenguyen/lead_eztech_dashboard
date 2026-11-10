/**
 * ==============================================================================
 * CÔNG CỤ ĐỒNG BỘ & LƯU BỀN VỮNG PANCAKE_STATE.JSON VÀO BẢNG APP_CONFIGS (NEON DB)
 * ==============================================================================
 * Hỗ trợ:
 * 1. Kiểm tra trạng thái: node scripts/sync_pancake_state.js --status
 * 2. Lưu file vào DB:   node scripts/sync_pancake_state.js <path_to_file.json>
 * 3. Xuất file từ DB:   node scripts/sync_pancake_state.js --export [output_file.json]
 * ==============================================================================
 */

const fs = require('fs');
const path = require('path');

// Đọc DATABASE_URL từ .env nếu chưa có trong process.env
function getDatabaseUrl() {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL.trim();
  const envPath = path.resolve(__dirname, '..', '.env');
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
    for (const line of lines) {
      const match = line.match(/^\s*DATABASE_URL\s*=\s*(.+)$/);
      if (match) {
        return match[1].trim().replace(/^['"]|['"]$/g, '');
      }
    }
  }
  return null;
}

const DATABASE_URL = getDatabaseUrl();
if (!DATABASE_URL) {
  console.error('❌ Không tìm thấy DATABASE_URL trong .env hoặc biến môi trường!');
  process.exit(1);
}

// Neon HTTP SQL endpoint
const matchHost = DATABASE_URL.match(/@([^/:]+)/);
if (!matchHost) {
  console.error('❌ DATABASE_URL không hợp lệ (không tìm thấy host).');
  process.exit(1);
}

const host = matchHost[1];
const sqlEndpoint = `https://${host}/sql`;

async function executeSql(query, params = []) {
  const cleanDbUrl = DATABASE_URL.replace(/[\?&]channel_binding=[^&]+/, '');
  const res = await fetch(sqlEndpoint, {
    method: 'POST',
    headers: {
      'Neon-Connection-String': cleanDbUrl,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ query, params })
  });

  const data = await res.json();
  if (data.message && data.code !== undefined && !data.rows) {
    throw new Error(data.message + (data.detail ? ` (${data.detail})` : ''));
  }
  return data.rows || [];
}

async function checkStatus() {
  console.log('🔍 Đang kiểm tra cấu hình pancake_state.json trong bảng app_configs...');
  const rows = await executeSql(`
    SELECT config_key, length(config_value) AS val_len, updated_at
    FROM app_configs
    WHERE config_key IN ('PANCAKE_STORAGE_STATE', 'pancake_storage_state', 'PANCAKE_STATE', 'pancake_state')
    ORDER BY updated_at DESC;
  `);

  if (!rows || rows.length === 0) {
    console.log('⚠️  Chưa có bản ghi pancake_state.json nào trong bảng app_configs.');
    console.log('👉 Bạn có thể lưu bằng lệnh: node scripts/sync_pancake_state.js <đường_dẫn_file.json>');
    return null;
  }

  console.log(`✅ Đã tìm thấy ${rows.length} bản ghi cấu hình phiên Pancake trong app_configs:`);
  for (const r of rows) {
    console.log(`   • Key: "${r.config_key}" | Dung lượng: ${r.val_len} bytes | Cập nhật lúc: ${r.updated_at}`);
  }
  return rows[0];
}

async function saveStateFromFile(filePath) {
  const absPath = path.resolve(process.cwd(), filePath);
  if (!fs.existsSync(absPath)) {
    console.error(`❌ File không tồn tại: ${absPath}`);
    process.exit(1);
  }

  const raw = fs.readFileSync(absPath, 'utf8').trim();
  if (!raw) {
    console.error('❌ Nội dung file rỗng.');
    process.exit(1);
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
    if (!parsed || (typeof parsed !== 'object') || (!parsed.cookies && !parsed.origins)) {
      throw new Error("Cần có trường 'cookies' hoặc 'origins'");
    }
  } catch (err) {
    console.error(`❌ File JSON không đúng định dạng Playwright storage_state: ${err.message}`);
    process.exit(1);
  }

  const cookiesCount = Array.isArray(parsed.cookies) ? parsed.cookies.length : 0;
  const originsCount = Array.isArray(parsed.origins) ? parsed.origins.length : 0;

  console.log(`📦 Đọc file: ${absPath}`);
  console.log(`   • Cookies: ${cookiesCount} | Origins: ${originsCount}`);
  console.log('🚀 Đang lưu bền vững vào bảng app_configs trên Neon DB...');

  // Lưu vào PANCAKE_STORAGE_STATE và đồng bộ pancake_storage_state
  const now = new Date().toISOString();
  await executeSql(`
    INSERT INTO app_configs (config_key, config_value, updated_at)
    VALUES ('PANCAKE_STORAGE_STATE', $1, NOW())
    ON CONFLICT (config_key)
    DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = NOW();
  `, [raw]);

  await executeSql(`
    INSERT INTO app_configs (config_key, config_value, updated_at)
    VALUES ('pancake_storage_state', $1, NOW())
    ON CONFLICT (config_key)
    DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = NOW();
  `, [raw]);

  // Đồng bộ ra file pancake_state.json ở thư mục gốc
  const rootTarget = path.resolve(process.cwd(), 'pancake_state.json');
  if (absPath !== rootTarget) {
    fs.writeFileSync(rootTarget, raw, 'utf8');
    console.log(`📁 Đã đồng bộ ra file: ${rootTarget}`);
  }

  console.log('🎉 THÀNH CÔNG! Đã lưu bền vững pancake_state.json vào bảng app_configs trong Neon DB.');
}

async function exportState(outputPath) {
  const targetFile = outputPath || path.resolve(process.cwd(), 'pancake_state.json');
  console.log('📥 Đang lấy pancake_state.json từ bảng app_configs...');

  const rows = await executeSql(`
    SELECT config_key, config_value, updated_at
    FROM app_configs
    WHERE config_key IN ('PANCAKE_STORAGE_STATE', 'pancake_storage_state', 'PANCAKE_STATE', 'pancake_state')
    ORDER BY updated_at DESC
    LIMIT 1;
  `);

  if (!rows || rows.length === 0 || !rows[0].config_value) {
    console.error('❌ Chưa có bản ghi pancake_state.json nào trong bảng app_configs để xuất.');
    process.exit(1);
  }

  const raw = rows[0].config_value;
  fs.writeFileSync(targetFile, raw, 'utf8');
  console.log(`✅ Đã xuất cấu hình (key: ${rows[0].config_key}) ra file: ${targetFile}`);
}

async function main() {
  const args = process.argv.slice(2);
  const command = args[0] || '--status';

  try {
    if (command === '--status' || command === '-s') {
      await checkStatus();
    } else if (command === '--export' || command === '-e') {
      await exportState(args[1]);
    } else {
      await saveStateFromFile(command);
    }
  } catch (err) {
    console.error('❌ Lỗi:', err.message);
    process.exit(1);
  }
}

main();
