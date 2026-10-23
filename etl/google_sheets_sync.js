/**
 * GOOGLE APPS SCRIPT ĐỒNG BỘ DEAL WIN / HỌC VIÊN SANG DATABASE NEON
 * 
 * Tính năng:
 * 1. onFormSubmitHandler: Tự động đẩy ngay khi có học viên mới nộp Form.
 * 2. onEditHandler: Tự động cập nhật ngay khi nhân viên sửa bất kỳ ô nào (Đóng tiền, Chăm sóc, Note...).
 * 3. dailySyncJob: Tự động chạy định kỳ mỗi ngày để quét và cập nhật toàn bộ bảng lên Neon.
 * 4. syncAllExistingDeals: Nút bấm đồng bộ thủ công trên thanh menu Google Sheet.
 */

// ĐỊA CHỈ API CỦA BẠN TRÊN RENDER (Gắn thêm /api/deals/webhook)
var API_URL = "https://pancake-lead-api.onrender.com/api/deals/webhook";
// MÃ BẢO MẬT WEBHOOK (Cấu hình giống với biến môi trường WEBHOOK_SECRET trên Render)
var WEBHOOK_SECRET = ""; 
var TARGET_SHEET_NAME = "Form Responses 1"; // Tên tab chứa kết quả form

/**
 * Lấy đúng sheet chứa dữ liệu form
 */
function getTargetSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(TARGET_SHEET_NAME) || ss.getActiveSheet();
}

/**
 * 1. TỰ ĐỘNG CHẠY KHI CÓ FORM MỚI NỘP
 */
function onFormSubmitHandler(e) {
  try {
    var sheet = getTargetSheet();
    var row = e ? e.range.getRow() : sheet.getLastRow();
    sendRowToBackend(sheet, row);
  } catch (err) {
    Logger.log("Lỗi onFormSubmitHandler: " + err);
  }
}

/**
 * 2. TỰ ĐỘNG CHẠY KHI NHÂN VIÊN SỬA BẤT KỲ Ô NÀO TRÊN SHEET (Real-time edit)
 * (Ví dụ: Đổi cột ĐÓNG TIỀN, HỌC KHÓA, CHĂM SÓC, Note...)
 */
function onEditHandler(e) {
  try {
    if (!e || !e.range) return;
    var sheet = e.range.getSheet();
    // Chỉ kích hoạt khi sửa trong sheet Form Responses 1 và từ dòng 2 trở đi
    if (sheet.getName() !== TARGET_SHEET_NAME && sheet.getName() !== getTargetSheet().getName()) return;
    var row = e.range.getRow();
    if (row < 2) return; // Bỏ qua dòng tiêu đề

    sendRowToBackend(sheet, row);
    Logger.log("Đã tự động cập nhật dòng " + row + " sau khi chỉnh sửa.");
  } catch (err) {
    Logger.log("Lỗi onEditHandler: " + err);
  }
}

/**
 * Gửi 1 dòng cụ thể sang Backend Neon
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
  
  var reqHeaders = {
    "Content-Type": "application/json"
  };
  if (WEBHOOK_SECRET && WEBHOOK_SECRET.trim() !== "") {
    reqHeaders["X-Webhook-Secret"] = WEBHOOK_SECRET.trim();
  }

  var options = {
    "method": "post",
    "contentType": "application/json",
    "headers": reqHeaders,
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  var postUrl = API_URL;
  if (WEBHOOK_SECRET && WEBHOOK_SECRET.trim() !== "" && API_URL.indexOf("?") === -1) {
    postUrl += "?secret=" + encodeURIComponent(WEBHOOK_SECRET.trim());
  }

  var response = UrlFetchApp.fetch(postUrl, options);
  Logger.log("Row " + rowNumber + " sent. Code: " + response.getResponseCode());
}

/**
 * 3. HÀM QUÉT ĐỒNG BỘ TOÀN BỘ SHEET LÊN NEON (CHẠY HÀNG NGÀY HOẶC THEO GIỜ)
 * Được thiết kế an toàn cho Trigger hẹn giờ (không dùng UI Alert để không bị lỗi)
 */
function dailySyncJob() {
  var sheet = getTargetSheet();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  
  if (lastRow < 2) {
    Logger.log("Sheet không có dữ liệu để đồng bộ.");
    return 0;
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
    Logger.log("Không có dòng dữ liệu hợp lệ.");
    return 0;
  }
  
  // Gửi theo từng lô 100 dòng lên Neon
  var batchSize = 100;
  var totalSent = 0;
  for (var i = 0; i < batch.length; i += batchSize) {
    var chunk = batch.slice(i, i + batchSize);
    var reqHeaders = {
      "Content-Type": "application/json"
    };
    if (WEBHOOK_SECRET && WEBHOOK_SECRET.trim() !== "") {
      reqHeaders["X-Webhook-Secret"] = WEBHOOK_SECRET.trim();
    }

    var options = {
      "method": "post",
      "contentType": "application/json",
      "headers": reqHeaders,
      "payload": JSON.stringify(chunk),
      "muteHttpExceptions": true
    };
    var postUrl = API_URL;
    if (WEBHOOK_SECRET && WEBHOOK_SECRET.trim() !== "" && API_URL.indexOf("?") === -1) {
      postUrl += "?secret=" + encodeURIComponent(WEBHOOK_SECRET.trim());
    }
    var response = UrlFetchApp.fetch(postUrl, options);
    totalSent += chunk.length;
    Logger.log("Đã gửi lô " + Math.floor(i / batchSize + 1) + ": " + chunk.length + " dòng. Status: " + response.getResponseCode());
  }
  
  Logger.log("Hoàn thành dailySyncJob: đã đồng bộ " + totalSent + " dòng lên Neon.");
  return totalSent;
}

/**
 * 4. NÚT BẤM THỦ CÔNG TỪ MENU GOOGLE SHEET (CÓ THÔNG BÁO POPUP)
 */
function syncAllExistingDeals() {
  try {
    var count = dailySyncJob();
    SpreadsheetApp.getUi().alert("Đã đồng bộ thành công " + count + " dòng học viên lên Database NEON!");
  } catch (err) {
    SpreadsheetApp.getUi().alert("Lỗi khi đồng bộ: " + err);
  }
}

/**
 * 5. TẠO MENU TIỆN ÍCH TRÊN GOOGLE SHEET
 */
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 EZTECH SYNC")
    .addItem("Đồng bộ toàn bộ Deal lên NEON", "syncAllExistingDeals")
    .addToUi();
}
