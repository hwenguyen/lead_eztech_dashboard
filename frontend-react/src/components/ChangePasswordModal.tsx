import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Lock, X, CheckCircle2, AlertCircle } from 'lucide-react';
import { changePasswordApi, type AuthUser } from '../services/api';
import { AccessibleModal } from './AccessibleModal';
import { showAppToast } from '../utils/toast';

interface ChangePasswordModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUserUpdated?: (user: AuthUser) => void;
}

export const ChangePasswordModal: React.FC<ChangePasswordModalProps> = ({ isOpen, onClose, onUserUpdated }) => {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const closeTimerRef = useRef<number | null>(null);

  const resetForm = useCallback(() => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setErrorMsg(null);
    setSuccessMsg(null);
    setLoading(false);
  }, []);

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [resetForm, onClose]);

  useEffect(() => {
    if (!isOpen) {
      resetForm();
    }
    return () => {
      if (closeTimerRef.current) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
    };
  }, [isOpen, resetForm]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || successMsg) return;
    setErrorMsg(null);
    setSuccessMsg(null);

    if (!oldPassword.trim() || !newPassword.trim() || !confirmPassword.trim()) {
      setErrorMsg('Vui lòng nhập đầy đủ cả 3 trường mật khẩu.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setErrorMsg('Xác nhận mật khẩu mới không trùng khớp.');
      return;
    }

    setLoading(true);
    try {
      const res = await changePasswordApi(oldPassword, newPassword, confirmPassword);
      const msg = res.message || 'Đổi mật khẩu thành công!';
      setSuccessMsg(msg);
      showAppToast(msg, 'success');
      if (res.user && onUserUpdated) {
        onUserUpdated(res.user);
      }
      closeTimerRef.current = window.setTimeout(() => {
        handleClose();
      }, 1500);
    } catch (err: any) {
      console.error('Lỗi đổi mật khẩu:', err);
      setErrorMsg(err.response?.data?.detail || 'Không thể đổi mật khẩu. Vui lòng kiểm tra lại mật khẩu cũ.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AccessibleModal
      isOpen={isOpen}
      onClose={handleClose}
      labelledBy="change-password-title"
      contentClassName="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-200 space-y-4"
    >
      <div className="flex items-center justify-between pb-3 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-brand-100 text-brand-600 flex items-center justify-center">
            <Lock className="w-4 h-4" />
          </div>
          <h3 id="change-password-title" className="text-sm font-bold text-navy">Đổi Mật Khẩu Tài Khoản</h3>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Đóng hộp thoại đổi mật khẩu"
          className="text-gray-400 hover:text-gray-600 p-1 rounded-lg"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {errorMsg && (
        <div role="alert" className="bg-red-50 text-red-700 px-3 py-2 rounded-xl text-xs flex items-center gap-2 border border-red-200">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div role="status" className="bg-emerald-50 text-emerald-700 px-3 py-2 rounded-xl text-xs flex items-center gap-2 border border-emerald-200">
          <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label htmlFor="cp-old-password" className="block text-xs font-semibold text-gray-700 mb-1">
            Mật khẩu hiện tại
          </label>
          <input
            id="cp-old-password"
            name="current_password"
            type="password"
            autoComplete="current-password"
            required
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            placeholder="Nhập mật khẩu cũ..."
            className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
          />
        </div>

        <div>
          <label htmlFor="cp-new-password" className="block text-xs font-semibold text-gray-700 mb-1">
            Mật khẩu mới
          </label>
          <input
            id="cp-new-password"
            name="new_password"
            type="password"
            autoComplete="new-password"
            required
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Nhập mật khẩu mới..."
            className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
          />
        </div>

        <div>
          <label htmlFor="cp-confirm-password" className="block text-xs font-semibold text-gray-700 mb-1">
            Xác nhận mật khẩu mới
          </label>
          <input
            id="cp-confirm-password"
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Nhập lại mật khẩu mới..."
            className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
          />
        </div>

        <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-gray-100">
          <button
            type="button"
            onClick={handleClose}
            className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-xl text-xs font-semibold"
          >
            Hủy bỏ
          </button>
          <button
            type="submit"
            disabled={loading || Boolean(successMsg)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm disabled:opacity-50"
          >
            {loading ? 'Đang lưu...' : successMsg ? 'Đã lưu' : 'Lưu mật khẩu mới'}
          </button>
        </div>
      </form>
    </AccessibleModal>
  );
};
