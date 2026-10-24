import React, { useState } from 'react';
import {
  Lock,
  User,
  Eye,
  EyeOff,
  ShieldCheck,
  AlertCircle,
  KeyRound,
  ArrowRight
} from 'lucide-react';
import { loginApi, type AuthUser } from '../services/api';

interface LoginPageProps {
  onLoginSuccess: (user: AuthUser) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setErrorMsg('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.');
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await loginApi(username.trim(), password, rememberMe);
      onLoginSuccess(res.user);
    } catch (err: any) {
      console.error('Lỗi đăng nhập:', err);
      const detail = err.response?.data?.detail;
      if (err.response?.status === 429) {
        setErrorMsg(detail || 'Tài khoản tạm thời bị khóa do thử sai quá 5 lần. Vui lòng thử lại sau.');
      } else if (err.response?.status === 401) {
        setErrorMsg(detail || 'Tên đăng nhập hoặc mật khẩu không chính xác.');
      } else {
        setErrorMsg(detail || 'Không thể kết nối đến máy chủ xác thực. Vui lòng thử lại sau.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-navy to-slate-950 flex items-center justify-center p-4 relative overflow-hidden text-gray-800">
      {/* Decorative Glow Elements */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="max-w-md w-full relative z-10">
        {/* Card Container */}
        <div className="bg-white/95 backdrop-blur-xl rounded-3xl shadow-2xl border border-white/20 p-8 sm:p-10 space-y-6">
          {/* Header & Logo */}
          <div className="text-center space-y-2">
            <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-gradient-to-tr from-indigo-50 to-blue-50 border border-indigo-100 shadow-inner mb-1">
              <img src="/logo.png" alt="EzTech Logo" className="h-12 object-contain" />
            </div>
            <h1 className="text-2xl font-extrabold text-navy tracking-tight">
              EzTech Lead Dashboard
            </h1>
            <p className="text-xs text-gray-500">
              Hệ thống Báo cáo & Tự động hóa Pancake
            </p>
          </div>

          {/* Error Banner */}
          {errorMsg && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-xs flex items-start gap-2.5 shadow-sm animate-shake">
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1 font-medium leading-relaxed">
                {errorMsg}
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username Input */}
            <div className="space-y-1.5">
              <label className="block text-xs font-bold text-gray-700">
                Tên đăng nhập
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                  <User className="w-4 h-4" />
                </div>
                <input
                  type="text"
                  required
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Nhập tên tài khoản..."
                  className="w-full pl-10 pr-4 py-2.5 bg-gray-50/80 border border-gray-300 rounded-xl text-xs text-gray-900 placeholder-gray-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition-all font-medium"
                />
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <label className="block text-xs font-bold text-gray-700">
                Mật khẩu
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Nhập mật khẩu..."
                  className="w-full pl-10 pr-10 py-2.5 bg-gray-50/80 border border-gray-300 rounded-xl text-xs text-gray-900 placeholder-gray-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition-all font-medium"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Remember Me Checkbox */}
            <div className="flex items-center justify-between pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                />
                <span className="text-xs text-gray-600 font-medium">Ghi nhớ đăng nhập (30 ngày)</span>
              </label>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 transition-all transform active:scale-[0.99] disabled:opacity-70 disabled:cursor-not-allowed mt-2"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  <span>Đăng Nhập</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Default Credentials Info Box */}
          <div className="bg-gradient-to-r from-blue-50/60 to-indigo-50/60 border border-indigo-100/80 rounded-2xl p-3.5 text-xs space-y-1.5">
            <div className="flex items-center gap-1.5 font-bold text-navy text-[11px]">
              <KeyRound className="w-3.5 h-3.5 text-indigo-600" />
              <span>Tài khoản Quản trị viên khởi tạo mặc định:</span>
            </div>
            <div className="flex items-center justify-between bg-white px-2.5 py-1.5 rounded-lg border border-indigo-100 font-mono text-[11px] text-gray-700">
              <span>Username: <strong className="text-indigo-700">admin</strong></span>
              <span>Mật khẩu: <strong className="text-indigo-700">eztech@2026</strong></span>
            </div>
            <p className="text-[10px] text-gray-500 italic">
              * Khuyến cáo đổi mật khẩu sau lần đăng nhập đầu tiên để đảm bảo an toàn.
            </p>
          </div>

          {/* Security Badges Footer */}
          <div className="pt-2 border-t border-gray-100 flex items-center justify-center gap-2 text-[11px] text-gray-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            <span>Mã hóa PBKDF2-HMAC-SHA256 & JWT Token HS256</span>
          </div>
        </div>
      </div>
    </div>
  );
};
