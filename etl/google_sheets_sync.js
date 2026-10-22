/**
 * GOOGLE APPS SCRIPT ĐỒNG BỘ DEAL WIN SANG DATABASE EZTECH
 * 
 * Hướng dẫn cài đặt trên Google Sheet:
 * 1. Trên trang Google Sheet (kết quả form), bấm: Tiện ích mở rộng (Extensions) > Apps Script
 * 2. Xóa code cũ, dán toàn bộ đoạn code này vào.
 * 3. Thay đổi biến API_URL bên dưới thành link Render của bạn:
 *    Ví dụ: "https://pancake-lead-api.onrender.com/api/deals/webhook"
 * 4. Bấm Lưu (Ctrl+S).
 * 5. Bấm Trình kích hoạt (Biểu tượng đồng hồ ở menu trái / Triggers) > Thêm trình kích hoạt:
 *    - Chọn hàm: onFormSubmitHandler
 *    - Chọn nguồn sự kiện: Từ bảng tính
 *    - Chọn loại sự kiện: Khi gửi biểu mẫu (On form submit)
 *    - Bấm Lưu và cấp quyền cho script.
 */

// ĐỊA CHỈ API CỦA BẠN TRÊN RENDER (Gắn thêm /api/deals/webhook)
var API_URL = "https://pancake-lead-api.onrender.com/api/deals/webhook";

/**
 * 1. TỰ ĐỘNG CHẠY KHI CÓ NGƯỜI NỘP FORM MỚI
 */
function onFormSubmitHandler(e) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    var row = e ? e.range.getRow() : sheet.getLastRow();
    sendRowToBackend(sheet, row);
  } catch (err) {
    Logger.log("Lỗi khi xử lý Form Submit: " + err);
  }
}

/**
 * 2. ĐỒNG BỘ 1 DÒNG CỤ THỂ SANG BACKEND
 */
function sendRowToBackend(sheet, rowNumber) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var rowValues = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getValues()[0];
  
  var payload = {
    "sheet_row_id": "row_" + rowNumber
  };
  
  for (var i = 0; i < headers.length; i++) {
    var header = String(headers[i]).trim();
    if (header) {
      var val = rowValues[i];
      if (val instanceof Date) {
        val = Utilities.formatDate(val, "Asia/Ho_Chi_Minh", "yyyy-MM-dd HH:mm:ss");
      }
      payload[header] = val;
    }
  }
  
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  var response = UrlFetchApp.fetch(API_URL, options);
  Logger.log("Row " + rowNumber + " sent. Response: " + response.getContentText());
}

/**
 * 3. NÚT BẤM ĐỒNG BỘ TOÀN BỘ SHEET LÊN DB (DÀNH CHO DỮ LIỆU CŨ ĐÃ CÓ SẴN)
 */
function syncAllExistingDeals() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert("Sheet không có dữ liệu để đồng bộ.");
    return;
  }
  
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var dataRange = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  
  var batch = [];
  for (var r = 0; r < dataRange.length; r++) {
    var rowNumber = r + 2;
    var rowValues = dataRange[r];
    var rowObj = {
      "sheet_row_id": "row_" + rowNumber
    };
    
    var hasData = false;
    for (var c = 0; c < headers.length; c++) {
      var header = String(headers[c]).trim();
      if (header) {
        var val = rowValues[c];
        if (val !== "" && val !== null && val !== undefined) {
          hasData = true;
        }
        if (val instanceof Date) {
          val = Utilities.formatDate(val, "Asia/Ho_Chi_Minh", "yyyy-MM-dd HH:mm:ss");
        }
        rowObj[header] = val;
      }
    }
    
    if (hasData) {
      batch.push(rowObj);
    }
  }
  
  if (batch.length === 0) {
    SpreadsheetApp.getUi().alert("Không có dòng dữ liệu hợp lệ.");
    return;
  }
  
  var batchSize = 100;
  var totalSent = 0;
  for (var i = 0; i < batch.length; i += batchSize) {
    var chunk = batch.slice(i, i + batchSize);
    var options = {
      "method": "post",
      "contentType": "application/json",
      "payload": JSON.stringify(chunk),
      "muteHttpExceptions": true
    };
    var response = UrlFetchApp.fetch(API_URL, options);
    totalSent += chunk.length;
  }
  
  SpreadsheetApp.getUi().alert("Đã đồng bộ thành công " + totalSent + " dòng Deal Win lên Database!");
}

/**
 * 4. TẠO MENU TIỆN ÍCH TRÊN GOOGLE SHEET
 */
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 EZTECH SYNC")
    .addItem("Đồng bộ toàn bộ Deal cũ lên DB", "syncAllExistingDeals")
    .addToUi();
}
