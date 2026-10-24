import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { Users, UserPlus, UserCheck, PhoneCall, PhoneForwarded, Percent, Calendar, RefreshCw, LayoutDashboard, Clock, Award, Bot, LogOut, KeyRound, Lock, Menu, X } from 'lucide-react';
import { KpiCard } from './components/KpiCard';
import { TrendChart } from './components/TrendChart';
import { LeadTable } from './components/LeadTable';
import { RatioChart } from './components/RatioChart';
import { StatsPieChart } from './components/StatsPieChart';
import { RemindLeadTable } from './components/RemindLeadTable';
import { DealWinDashboard } from './components/DealWinDashboard';
import { BulkMessengerDashboard } from './components/BulkMessengerDashboard';
import { LoginPage } from './components/LoginPage';
import { ChangePasswordModal } from './components/ChangePasswordModal';
import { fetchSummary, fetchTrend, fetchLeads, fetchEmployees, fetchPages, getStoredAuth, logoutApi, type SummaryData, type TrendData, type Lead, type AuthUser } from './services/api';

function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => getStoredAuth().user);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!getStoredAuth().token);
  const [showChangePw, setShowChangePw] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);

  useEffect(() => {
    const onUnauthorized = () => {
      setIsAuthenticated(false);
      setCurrentUser(null);
    };
    window.addEventListener('auth_unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth_unauthorized', onUnauthorized);
  }, []);

  const handleLogout = async () => {
    if (window.confirm('Bạn có chắc chắn muốn đăng xuất không?')) {
      await logoutApi();
      setIsAuthenticated(false);
      setCurrentUser(null);
    }
  };

  const [activeTab, setActiveTab] = useState<'overview' | 'remind' | 'deals' | 'bot'>('overview');
  const [startDate, setStartDate] = useState(format(subDays(new Date(), 7), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pageId, setPageId] = useState('');
  const [employee, setEmployee] = useState('');
  const [employeesList, setEmployeesList] = useState<string[]>([]);
  const [pagesList, setPagesList] = useState<string[]>([]);
  const [zaloPages, setZaloPages] = useState<string[]>([]);

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [phoneCategoryFilter, setPhoneCategoryFilter] = useState<'all' | 'new' | 'recontact'>('all');

  useEffect(() => {
    const loadPages = async () => {
      try {
        const pgRes = await fetchPages();
        setPagesList(pgRes.pages);
        setZaloPages(pgRes.zaloPages);
      } catch (error) {
        console.error("Error fetching pages:", error);
      }
    };
    loadPages();
  }, []);

  useEffect(() => {
    const updateEmployees = async () => {
      try {
        const empRes = await fetchEmployees(startDate, endDate, pageId);
        setEmployeesList(empRes);
        setEmployee(prev => (prev && !empRes.includes(prev) ? '' : prev));
      } catch (error) {
        console.error("Error fetching employees:", error);
      }
    };
    updateEmployees();
  }, [startDate, endDate, pageId]);

  const loadData = async () => {
    setLoading(true);
    try {
      const sumPromise = fetchSummary(startDate, endDate, pageId, employee).catch(err => {
        console.error("Summary error:", err);
        return null;
      });
      const trPromise = fetchTrend(startDate, endDate, pageId, employee).catch(err => {
        console.error("Trend error:", err);
        return [];
      });
      const ldPromise = fetchLeads(pageId, employee, startDate, endDate, 1, pageSize).catch(err => {
        console.error("Leads error:", err);
        return { data: [], total: 0, page: 1, size: pageSize };
      });

      const [sumRes, trRes, ldRes] = await Promise.all([sumPromise, trPromise, ldPromise]);
      if (sumRes) setSummary(sumRes);
      if (trRes) setTrend(trRes);
      if (ldRes) {
        setLeads(ldRes.data);
        setTotalLeads(ldRes.total);
      }
      setPage(1);
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadLeadsPage = async (newPage: number) => {
    try {
      const ldRes = await fetchLeads(pageId, employee, startDate, endDate, newPage, pageSize);
      setLeads(ldRes.data);
      setTotalLeads(ldRes.total);
      setPage(newPage);
    } catch (error) {
      console.error("Error fetching leads:", error);
    }
  };

  useEffect(() => {
    loadData();
  }, [startDate, endDate, pageId, employee]);

  const newLeadsCount = summary?.new_leads || 0;
  const recontactLeadsCount = summary?.recontact_leads || 0;
  const totalLeadsCount = summary?.total_leads || 0;
  const newPhoneCount = summary?.new_phone_leads || 0;
  const recontactPhoneCount = summary?.recontact_phone_leads || 0;

  const pct = (part: number, whole: number) => (whole > 0 ? (part / whole) * 100 : 0).toFixed(1);

  const navItems = [
    { id: 'overview' as const, label: 'Tổng quan & Chỉ số', icon: LayoutDashboard },
    { id: 'remind' as const, label: 'Chăm sóc Lead', icon: Clock },
    { id: 'deals' as const, label: 'Deal Win', icon: Award },
    { id: 'bot' as const, label: 'Bot Gửi Tin', icon: Bot, badge: 'Pancake' },
  ];

  return (
    <div className="min-h-screen bg-bg-page text-foreground flex">
      {/* 1. Backdrop on Mobile */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-navy/40 z-30 lg:hidden backdrop-blur-xs transition-opacity"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* 2. Left Sidebar Navigation */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-60 bg-white border-r border-slate-200/80 flex flex-col transition-transform duration-300 ease-in-out lg:static lg:translate-x-0 ${
          isSidebarOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'
        }`}
      >
        {/* Brand / Logo Header */}
        <div className="h-14 px-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <img src="/logo.png" alt="EzTech Logo" className="h-7 object-contain" />
            <div className="border-l border-slate-200 pl-2.5">
              <h1 className="text-xs font-bold text-navy tracking-tight leading-none">Lead Analytics</h1>
              <p className="text-[10px] text-slate-400 mt-0.5 font-medium">EzTech CRM</p>
            </div>
          </div>
          <button
            onClick={() => setIsSidebarOpen(false)}
            className="lg:hidden p-1.5 text-slate-400 hover:text-navy rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Navigation Menu */}
        <div className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400 mb-2">
            Không gian làm việc
          </p>

          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => { setActiveTab(item.id); setIsSidebarOpen(false); }}
                className={`group relative w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs transition-all ${
                  isActive
                    ? 'bg-eztech-light text-eztech font-semibold'
                    : 'text-slate-600 font-medium hover:text-navy hover:bg-slate-50'
                }`}
              >
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-eztech" />
                )}
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 transition-colors ${
                      isActive ? 'text-eztech' : 'text-slate-400 group-hover:text-navy'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>
                {item.badge ? (
                  <span
                    className={`px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded ${
                      isActive
                        ? 'bg-gold text-navy'
                        : 'bg-gold-light text-gold-dark border border-gold-border/70'
                    }`}
                  >
                    {item.badge}
                  </span>
                ) : (
                  isActive && <div className="w-1.5 h-1.5 rounded-full bg-gold" />
                )}
              </button>
            );
          })}
        </div>

        {/* Bottom User Profile Section in Sidebar */}
        <div className="p-3 border-t border-slate-100 bg-slate-50/50">
          {isAuthenticated ? (
            <div className="p-2.5 bg-white border border-slate-200/80 rounded-xl shadow-card space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-navy text-gold text-xs font-bold flex items-center justify-center uppercase shrink-0">
                  {(currentUser?.username || 'A').slice(0, 2)}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="block text-xs font-semibold text-navy truncate">
                    {currentUser?.username || 'admin'}
                  </span>
                  <span className="inline-block text-[10px] text-eztech font-semibold uppercase bg-eztech-light px-1.5 py-0.2 rounded">
                    {currentUser?.role || 'admin'}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1.5 pt-1.5 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowChangePw(true)}
                  className="flex-1 py-1.5 px-2 text-[11px] font-medium text-slate-600 hover:text-eztech hover:bg-eztech-light rounded-lg flex items-center justify-center gap-1 transition-colors"
                >
                  <KeyRound className="w-3.5 h-3.5" />
                  <span>Đổi mật khẩu</span>
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="py-1.5 px-2 text-[11px] font-medium text-rose-600 hover:bg-rose-50 rounded-lg flex items-center justify-center gap-1 transition-colors"
                  title="Đăng xuất"
                >
                  <LogOut className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => { setActiveTab('bot'); setIsSidebarOpen(false); }}
              className="w-full py-2 px-3 bg-white hover:bg-eztech-light text-navy hover:text-eztech border border-slate-200/90 hover:border-eztech-border rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition-all shadow-card"
            >
              <Lock className="w-3.5 h-3.5 text-eztech" />
              <span>Đăng nhập Bot</span>
            </button>
          )}
        </div>
      </aside>

      {/* 3. Main Content Area */}
      <div className="flex-1 min-w-0 flex flex-col min-h-screen">
        {/* Top Header */}
        <header className="bg-white/85 backdrop-blur-md border-b border-slate-200/80 sticky top-0 z-20 h-14">
          <div className="px-4 sm:px-6 lg:px-8 h-full flex items-center justify-between max-w-[1440px] mx-auto w-full">
            {/* Left: Mobile hamburger & Active Tab Title */}
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-1.5 text-slate-600 hover:text-navy hover:bg-slate-100 rounded-lg transition-colors"
              >
                <Menu className="w-5 h-5" />
              </button>
              <div className="flex items-baseline gap-2.5">
                <h2 className="text-[15px] sm:text-base font-bold text-navy tracking-tight">
                  {activeTab === 'overview' && 'Tổng quan & Chỉ số'}
                  {activeTab === 'remind' && 'Chăm sóc Lead (Remind)'}
                  {activeTab === 'deals' && 'Học viên Chốt (Deal Win)'}
                  {activeTab === 'bot' && 'Bot Gửi Tin Nhắn Tự Động'}
                </h2>
                <span className="hidden md:inline-block text-xs text-slate-400">
                  • Hệ thống phân tích dữ liệu Pancake
                </span>
              </div>
            </div>

            {/* Right: Last updated & Refresh button */}
            <div className="flex items-center gap-3">
              {lastUpdated && (
                <span className="text-[11px] font-mono text-slate-400 hidden sm:inline-block tabular-nums">
                  Cập nhật {format(lastUpdated, 'HH:mm')}
                </span>
              )}
              <button
                onClick={loadData}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-white hover:bg-eztech-light rounded-lg transition-all border border-slate-200/90 hover:border-eztech-border text-navy hover:text-eztech shadow-card"
              >
                <RefreshCw className={`w-3.5 h-3.5 text-eztech ${loading ? 'animate-spin' : ''}`} />
                <span>Làm mới</span>
              </button>
            </div>
          </div>
        </header>

        {/* Content Body */}
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-5 space-y-4 max-w-[1440px] w-full mx-auto">
          {activeTab === 'deals' ? (
            <DealWinDashboard />
          ) : activeTab === 'remind' ? (
            <RemindLeadTable pagesList={pagesList} zaloPages={zaloPages} />
          ) : activeTab === 'bot' ? (
            !isAuthenticated ? (
              <LoginPage
                embedded={true}
                onLoginSuccess={(user) => {
                  setCurrentUser(user);
                  setIsAuthenticated(true);
                }}
              />
            ) : (
              <BulkMessengerDashboard />
            )
          ) : (
            <>
              {/* Compact Inline Filter Toolbar */}
              <div className="bg-white rounded-xl border border-slate-200/80 shadow-card px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                {/* Date Range Group */}
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-navy mr-1">
                    <Calendar className="w-3.5 h-3.5 text-eztech" />
                    <span>Kỳ báo cáo</span>
                  </div>
                  <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 py-1">
                    <input
                      type="date"
                      value={startDate}
                      onChange={e => setStartDate(e.target.value)}
                      className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
                    />
                    <span className="text-slate-300 text-xs">→</span>
                    <input
                      type="date"
                      value={endDate}
                      onChange={e => setEndDate(e.target.value)}
                      className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
                    />
                  </div>
                </div>

                {/* Page & Employee Selectors */}
                <div className="flex flex-wrap items-center gap-2.5 flex-1 sm:justify-end">
                  <div className="flex items-center gap-2 min-w-[220px] flex-1 sm:flex-initial">
                    <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider shrink-0">Page</span>
                    <select
                      value={pageId}
                      onChange={e => setPageId(e.target.value)}
                      className="w-full px-2.5 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
                    >
                      <option value="">Tất cả page nguồn lead (trừ Zalo)</option>
                      <optgroup label="Nguồn lead">
                        {pagesList.filter(pg => !zaloPages.includes(pg)).map(pg => (
                          <option key={pg} value={pg}>{pg}</option>
                        ))}
                      </optgroup>
                      {zaloPages.length > 0 && (
                        <optgroup label="Zalo (chăm sóc)">
                          {zaloPages.map(pg => (
                            <option key={pg} value={pg}>{pg}</option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </div>

                  <div className="flex items-center gap-2 min-w-[190px] flex-1 sm:flex-initial">
                    <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider shrink-0">Nhân sự</span>
                    <select
                      value={employee}
                      onChange={e => setEmployee(e.target.value)}
                      className="w-full px-2.5 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
                    >
                      <option value="">Tất cả nhân viên</option>
                      {employeesList.map(emp => (
                        <option key={emp} value={emp}>{emp}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-24">
                  <div className="flex flex-col items-center gap-3">
                    <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-200 border-t-eztech" />
                    <p className="text-xs font-medium text-slate-400">Đang đồng bộ dữ liệu...</p>
                  </div>
                </div>
              ) : (
                <>
                  {/* KPIs - 6 cards: Unified EzTech Navy/Blue for Leads & EzTech Gold for Phone Conversions */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3.5">
                    <KpiCard
                      title="Tổng Lead"
                      value={totalLeadsCount.toLocaleString()}
                      subtitle="Mới + Contact lại"
                      icon={<Users className="w-4 h-4" />}
                      color="navy"
                    />
                    <KpiCard
                      title="Lead Mới"
                      value={newLeadsCount.toLocaleString()}
                      subtitle={`${pct(newLeadsCount, totalLeadsCount)}% tổng lead`}
                      icon={<UserPlus className="w-4 h-4" />}
                      color="blue"
                    />
                    <KpiCard
                      title="Lead Contact Lại"
                      value={recontactLeadsCount.toLocaleString()}
                      subtitle={`${pct(recontactLeadsCount, totalLeadsCount)}% tổng lead`}
                      icon={<UserCheck className="w-4 h-4" />}
                      color="blue"
                    />
                    <KpiCard
                      title="SĐT Mới"
                      value={newPhoneCount.toLocaleString()}
                      subtitle="Từ lead tạo trong kỳ"
                      icon={<PhoneCall className="w-4 h-4" />}
                      color="gold"
                    />
                    <KpiCard
                      title="SĐT Contact Lại"
                      value={recontactPhoneCount.toLocaleString()}
                      subtitle="Từ lead cũ tương tác"
                      icon={<PhoneForwarded className="w-4 h-4" />}
                      color="gold"
                    />
                    <KpiCard
                      title="SĐT / Tạo mới"
                      value={`${pct(newPhoneCount, newLeadsCount)}%`}
                      subtitle={`${newPhoneCount.toLocaleString()} / ${newLeadsCount.toLocaleString()} lead mới`}
                      icon={<Percent className="w-4 h-4" />}
                      color="gold"
                      highlight={true}
                    />
                  </div>

                  {/* Charts row */}
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
                    <div className="lg:col-span-3">
                      <TrendChart data={trend} />
                    </div>
                    <div className="lg:col-span-1">
                      <RatioChart
                        newLeads={newLeadsCount}
                        recontactLeads={recontactLeadsCount}
                        totalLeads={totalLeadsCount}
                        newPhoneLeads={newPhoneCount}
                      />
                    </div>
                  </div>

                  {/* Additional Charts Row */}
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    <StatsPieChart
                      title="Lead Mới / Nhân viên"
                      subtitle="Phân bổ Lead Mới theo nhân sự"
                      stats={summary?.new_leads_employee_stats}
                    />
                    <StatsPieChart
                      title={
                        phoneCategoryFilter === 'new'
                          ? "SĐT Mới / Lead Other & Đào tạo"
                          : phoneCategoryFilter === 'recontact'
                          ? "SĐT Contact lại / Lead Other & Đào tạo"
                          : "SĐT thu được / Lead Other & Đào tạo"
                      }
                      subtitle={
                        phoneCategoryFilter === 'new'
                          ? "Phân bổ SĐT từ Lead Mới"
                          : phoneCategoryFilter === 'recontact'
                          ? "Phân bổ SĐT từ Lead Contact lại"
                          : "Phân bổ Tổng SĐT thu được trong kỳ"
                      }
                      stats={
                        phoneCategoryFilter === 'new'
                          ? summary?.new_phone_tag_stats
                          : phoneCategoryFilter === 'recontact'
                          ? summary?.recontact_phone_tag_stats
                          : summary?.phone_tag_stats
                      }
                      unit="SĐT"
                      headerAction={
                        <select
                          value={phoneCategoryFilter}
                          onChange={(e) => setPhoneCategoryFilter(e.target.value as 'all' | 'new' | 'recontact')}
                          className="text-[11px] font-semibold text-eztech bg-eztech-light border border-eztech-border rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-eztech/20 cursor-pointer hover:bg-eztech-border/50 transition-colors tabular-nums"
                        >
                          <option value="all">Tổng SĐT{summary ? ` (${summary.phone_leads})` : ''}</option>
                          <option value="new">SĐT Mới{summary ? ` (${summary.new_phone_leads})` : ''}</option>
                          <option value="recontact">SĐT Contact lại{summary ? ` (${summary.recontact_phone_leads})` : ''}</option>
                        </select>
                      }
                      colorMap={{
                        'Lead Other': '#1E5BD6',
                        'Đào tạo': '#0A1F44',
                        'Other': '#F5B400',
                      }}
                    />
                    <StatsPieChart
                      title="Tổng Lead / Lead Other & Đào tạo"
                      subtitle="Thống kê Tag phân loại (tất cả Lead)"
                      stats={summary?.tag_stats}
                      colorMap={{
                        'Lead Other': '#1E5BD6',
                        'Đào tạo': '#0A1F44',
                        'Other': '#F5B400',
                      }}
                    />
                  </div>

                  {/* Table */}
                  <LeadTable
                    leads={leads}
                    totalLeads={totalLeads}
                    page={page}
                    pageSize={pageSize}
                    onPageChange={loadLeadsPage}
                  />
                </>
              )}
            </>
          )}
        </main>
      </div>

      <ChangePasswordModal
        isOpen={showChangePw}
        onClose={() => setShowChangePw(false)}
      />
    </div>
  );
}

export default App;
