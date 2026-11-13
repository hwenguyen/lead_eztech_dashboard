/**
 * Google Apps Script - Đồng bộ LIVE Bảng Nhập Deal & Công Nợ (EzTech)
 *
 * Cách cài đặt (1 phút):
 * 1. Mở Google Sheet cần đồng bộ -> menu Tiện ích mở rộng (Extensions) -> Apps Script.
 * 2. Xóa hết code mặc định, dán toàn bộ file này vào -> bấm Lưu (Ctrl+S).
 * 3. Bấm Triển khai (Deploy) -> Tùy chọn triển khai mới (New deployment):
 *    - Loại: Ứng dụng web (Web app)
 *    - Thực thi dưới tư cách (Execute as): Tôi (Me)
 *    - Người có quyền truy cập (Who has access): Bất kỳ ai (Anyone)
 * 4. Copy URL Web App (.../exec) dán vào nút "Google Sheet Live" trên web.
 */

var SHEET_NAME = 'Deals';

var HEADERS = [
  'ID',
  'Ngày thu tiền',
  'Ngày contact đầu tiên',
  'Số điện thoại',
  'Họ tên',
  'Email',
  'Năm sinh',
  'Địa chỉ',
  'Lĩnh vực',
  'Chức vụ',
  'Kỳ vọng',
  'Zalo (link Pancake)',
  'Nhóm CS 1-1',
  'Chương trình học',
  'Lớp học',
  'NV chăm sóc',
  'Zalo chăm sóc',
  'Nguồn',
  'Số tiền thu được',
  'Phải thu khách hàng',
  'Tổng tiền',
  'Ngày thu AR',
  'Trạng thái',
  'Note',
  'Người nhập',
  'Tạo lúc',
  'Trong đó thu nợ cũ',
  'Đã thu nợ',
  'Còn nợ'
];

function getTargetSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#f1f5f9');
  } else {
    var firstRow = sheet.getRange(1, 1, 1, HEADERS.length).getValues()[0];
    if (String(firstRow[0] || '').trim() !== 'ID') {
      sheet.insertRowBefore(1);
      sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
      sheet.setFrozenRows(1);
      sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#f1f5f9');
    }
  }
  return sheet;
}

function rowObjectToArray_(r) {
  var phoneText = r.sdt ? "'" + String(r.sdt).replace(/^'/, '') : '';
  return [
    r.id || '',
    r.ngayThu || '',
    r.ngayContact || '',
    phoneText,
    r.hoTen || '',
    r.email || '',
    r.namSinh || '',
    r.diaChi || '',
    r.linhVuc || '',
    r.chucVu || '',
    r.kyVong || '',
    r.zalo || '',
    r.nhomCS || '',
    r.chuongTrinh || '',
    r.lop || '',
    r.nvCS || '',
    r.zaloCS || '',
    r.nguon || '',
    Number(r.daThu || 0),
    Number(r.phaiThu || 0),
    Number(r.tongTien || 0),
    r.ngayThuAR || '',
    r.trangThai || '',
    r.note || '',
    r.nguoiNhap || '',
    r.taoLuc || '',
    Number(r.thuNo || 0),
    Number(r.daThuNo || 0),
    Number(r.conNo || 0)
  ];
}

function findIdRowMap_(sheet) {
  var lastRow = sheet.getLastRow();
  var map = {};
  if (lastRow < 2) return map;
  var idValues = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  for (var i = 0; i < idValues.length; i++) {
    var idStr = String(idValues[i][0] || '').trim();
    if (idStr) {
      map[idStr] = i + 2; // 1-based sheet row index
    }
  }
  return map;
}

function upsertRows_(sheet, rows) {
  if (!rows || !rows.length) return 0;
  var idMap = findIdRowMap_(sheet);
  var toInsert = [];
  var updated = 0;

  for (var i = 0; i < rows.length; i++) {
    var item = rows[i];
    var id = String(item.id || '').trim();
    if (!id) continue;
    var arr = rowObjectToArray_(item);
    var existingRow = idMap[id];
    if (existingRow) {
      sheet.getRange(existingRow, 1, 1, HEADERS.length).setValues([arr]);
      updated++;
    } else {
      toInsert.push(arr);
    }
  }

  if (toInsert.length > 0) {
    // Chèn giao dịch mới ngay sau dòng tiêu đề để dễ theo dõi trên cùng
    sheet.insertRowsAfter(1, toInsert.length);
    sheet.getRange(2, 1, toInsert.length, HEADERS.length).setValues(toInsert);
  }
  return updated + toInsert.length;
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    var raw = (e && e.postData && e.postData.contents) ? e.postData.contents : '{}';
    var data = JSON.parse(raw);
    var action = data.action || 'upsert_phone';
    var sheet = getTargetSheet_();

    if (action === 'replace_all') {
      var allRows = data.rows || [];
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        sheet.getRange(2, 1, lastRow - 1, HEADERS.length).clearContent();
      }
      if (allRows.length > 0) {
        var values = [];
        for (var i = 0; i < allRows.length; i++) {
          values.push(rowObjectToArray_(allRows[i]));
        }
        sheet.getRange(2, 1, values.length, HEADERS.length).setValues(values);
      }
      return ContentService
        .createTextOutput(JSON.stringify({ ok: true, synced: allRows.length }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (action === 'delete') {
      var delId = String(data.deal_id || '').trim();
      if (delId) {
        var idMap = findIdRowMap_(sheet);
        if (idMap[delId]) {
          sheet.deleteRow(idMap[delId]);
        }
      }
      if (data.rows && data.rows.length) {
        upsertRows_(sheet, data.rows);
      }
      return ContentService
        .createTextOutput(JSON.stringify({ ok: true, deleted: delId }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Mặc định: upsert_phone (cập nhật/thêm các giao dịch của SĐT vừa sửa)
    var count = upsertRows_(sheet, data.rows || []);
    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, upserted: count }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, service: 'EzTech Deal Live Sheet' }))
    .setMimeType(ContentService.MimeType.JSON);
}
