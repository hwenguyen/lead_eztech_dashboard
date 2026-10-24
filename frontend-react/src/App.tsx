import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { Users, UserPlus, UserCheck, PhoneCall, PhoneForwarded, Percent, Filter, RefreshCw, LayoutDashboard, Clock, Award, Bot, LogOut, KeyRound, Lock, Menu, X } from 'lucide-react';
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

  return (
    <div className="min-h-screen bg-bg-page text-[#111827] flex">
      {/* 1. Backdrop on Mobile */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden backdrop-blur-sm transition-opacity"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* 2. Left Sidebar Navigation */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-white border-r border-[#E5E7EB] flex flex-col transition-transform duration-300 ease-in-out lg:static lg:translate-x-0 ${
          isSidebarOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'
        }`}
      >
        {/* Brand / Logo Header */}
        <div className="h-16 px-5 border-b border-[#E5E7EB] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="EzTech Logo" className="h-9 object-contain" />
            <div className="border-l border-[#E5E7EB] pl-2.5">
              <h1 className="text-xs font-bold text-navy leading-none">Lead Dashboard</h1>
              <p className="text-[10px] text-[#4B5563] mt-1 font-medium">Pancake Analytics</p>
            </div>
          </div>
          <button
            onClick={() => setIsSidebarOpen(false)}
            className="lg:hidden p-1.5 text-gray-500 hover:text-navy rounded-lg"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation Menu */}
        <div className="flex-1 px-3 py-4 space-y-1.5 overflow-y-auto">
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">
            Menu Quản Lý
          </p>

          {/* Tab 1: Overview */}
          <button
            onClick={() => { setActiveTab('overview'); setIsSidebarOpen(false); }}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
              activeTab === 'overview'
                ? 'bg-blue-50 text-blue-700 shadow-sm font-bold'
                : 'text-gray-600 hover:text-navy hover:bg-gray-100/80'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <LayoutDashboard className={`w-4 h-4 ${activeTab === 'overview' ? 'text-blue-600' : 'text-gray-400'}`} />
              <span>Tổng quan & Chỉ số</span>
            </div>
            {activeTab === 'overview' && <div className="w-1.5 h-1.5 rounded-full bg-blue-600" />}
          </button>

          {/* Tab 2: Remind */}
          <button
            onClick={() => { setActiveTab('remind'); setIsSidebarOpen(false); }}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
              activeTab === 'remind'
                ? 'bg-amber-50 text-amber-800 shadow-sm font-bold'
                : 'text-gray-600 hover:text-navy hover:bg-gray-100/80'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <Clock className={`w-4 h-4 ${activeTab === 'remind' ? 'text-amber-500' : 'text-gray-400'}`} />
              <span>Chăm sóc Lead</span>
            </div>
            {activeTab === 'remind' && <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
          </button>

          {/* Tab 3: Deals */}
          <button
            onClick={() => { setActiveTab('deals'); setIsSidebarOpen(false); }}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
              activeTab === 'deals'
                ? 'bg-emerald-50 text-emerald-800 shadow-sm font-bold'
                : 'text-gray-600 hover:text-navy hover:bg-gray-100/80'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <Award className={`w-4 h-4 ${activeTab === 'deals' ? 'text-emerald-600' : 'text-gray-400'}`} />
              <span>Deal Win</span>
            </div>
            {activeTab === 'deals' && <div className="w-1.5 h-1.5 rounded-full bg-emerald-600" />}
          </button>

          {/* Tab 4: Bot Gửi Tin */}
          <button
            onClick={() => { setActiveTab('bot'); setIsSidebarOpen(false); }}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
              activeTab === 'bot'
                ? 'bg-indigo-50 text-indigo-700 shadow-sm font-bold'
                : 'text-gray-600 hover:text-navy hover:bg-gray-100/80'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <Bot className={`w-4 h-4 ${activeTab === 'bot' ? 'text-indigo-600' : 'text-gray-400'}`} />
              <span>Bot Gửi Tin</span>
            </div>
            <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-indigo-100 text-indigo-700 rounded-md">
              Pancake
            </span>
          </button>
        </div>

        {/* Bottom User Profile Section in Sidebar */}
        <div className="p-3 border-t border-[#E5E7EB] bg-gray-50/50">
          {isAuthenticated ? (
            <div className="p-2.5 bg-white border border-gray-200 rounded-xl shadow-sm space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-600 to-blue-500 text-white text-xs font-bold flex items-center justify-center uppercase shadow-sm">
                  {(currentUser?.username || 'A').slice(0, 2)}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="block text-xs font-bold text-navy truncate">
                    {currentUser?.username || 'admin'}
                  </span>
                  <span className="inline-block text-[10px] text-indigo-600 font-bold uppercase bg-indigo-50 px-1.5 py-0.2 rounded">
                    {currentUser?.role || 'admin'}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1.5 pt-1.5 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setShowChangePw(true)}
                  className="flex-1 py-1.5 px-2 text-[11px] font-medium text-gray-600 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg flex items-center justify-center gap-1 transition-colors"
                >
                  <KeyRound className="w-3.5 h-3.5" />
                  <span>Đổi mật khẩu</span>
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="py-1.5 px-2 text-[11px] font-medium text-red-600 hover:bg-red-50 rounded-lg flex items-center justify-center gap-1 transition-colors"
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
              className="w-full py-2 px-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-colors shadow-sm"
            >
              <Lock className="w-3.5 h-3.5 text-indigo-600" />
              <span>Đăng nhập Bot</span>
            </button>
          )}
        </div>
      </aside>

      {/* 3. Main Content Area */}
      <div className="flex-1 min-w-0 flex flex-col min-h-screen">
        {/* Top Header */}
        <header className="bg-white border-b border-[#E5E7EB] sticky top-0 z-20 shadow-sm h-16">
          <div className="px-4 sm:px-6 lg:px-8 h-full flex items-center justify-between">
            {/* Left: Mobile hamburger & Active Tab Title */}
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-2 text-gray-600 hover:text-navy hover:bg-gray-100 rounded-xl transition-colors"
              >
                <Menu className="w-5 h-5" />
              </button>
              <div>
                <h2 className="text-sm sm:text-base font-bold text-navy leading-none">
                  {activeTab === 'overview' && 'Tổng quan & Chỉ số'}
                  {activeTab === 'remind' && 'Chăm sóc Lead (Remind)'}
                  {activeTab === 'deals' && 'Học viên Chốt (Deal Win)'}
                  {activeTab === 'bot' && 'Bot Gửi Tin Nhắn Tự Động'}
                </h2>
                <p className="text-[11px] text-[#4B5563] mt-1 hidden sm:block">
                  Hệ thống phân tích & tự động hóa dữ liệu Pancake
                </p>
              </div>
            </div>

            {/* Right: Last updated & Refresh button */}
            <div className="flex items-center gap-3">
              {lastUpdated && (
                <span className="text-xs text-[#4B5563] hidden sm:inline-block">
                  Cập nhật: {format(lastUpdated, 'HH:mm')}
                </span>
              )}
              <button
                onClick={loadData}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-light-blue/50 hover:bg-light-blue rounded-lg transition-colors border border-transparent hover:border-[#1E5BD6]/20 text-[#1E5BD6]"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Làm mới</span>
              </button>
            </div>
          </div>
        </header>

        {/* Content Body */}
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
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
            {/* Filter Panel */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm p-5">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="w-4 h-4 text-eztech" />
            <span className="text-sm font-semibold text-navy">Bộ lọc</span>
          </div>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-[#4B5563]">Từ ngày</label>
              <input
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827]"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-[#4B5563]">Đến ngày</label>
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827]"
              />
            </div>
            <div className="h-9 w-px bg-[#E5E7EB] mx-1" />
              <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
                <label className="text-xs font-medium text-[#4B5563]">Page</label>
                <select
                  value={pageId}
                  onChange={e => setPageId(e.target.value)}
                  className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827] cursor-pointer"
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
            <div className="flex flex-col gap-1 min-w-[200px]">
              <label className="text-xs font-medium text-[#4B5563]">Nhân Viên</label>
              <select
                value={employee}
                onChange={e => setEmployee(e.target.value)}
                className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827]"
              >
                <option value="">-- Tất cả nhân viên --</option>
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
              <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-200 border-t-blue-600" />
              <p className="text-sm text-gray-400">Đang tải dữ liệu...</p>
            </div>
          </div>
        ) : (
          <>
            {/* KPIs - 6 cards: hàng Lead, hàng SĐT */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <KpiCard
                title="Tổng Lead"
                value={totalLeadsCount.toLocaleString()}
                subtitle="Mới + Contact lại trong kỳ"
                icon={<Users className="w-5 h-5" />}
                color="indigo"
              />
              <KpiCard
                title="Lead Mới"
                value={newLeadsCount.toLocaleString()}
                subtitle={`${pct(newLeadsCount, totalLeadsCount)}% tổng lead`}
                icon={<UserPlus className="w-5 h-5" />}
                color="blue"
              />
              <KpiCard
                title="Lead Contact Lại"
                value={recontactLeadsCount.toLocaleString()}
                subtitle={`${pct(recontactLeadsCount, totalLeadsCount)}% tổng lead`}
                icon={<UserCheck className="w-5 h-5" />}
                color="green"
              />
              <KpiCard
                title="SĐT Mới"
                value={newPhoneCount.toLocaleString()}
                subtitle="SĐT thu từ lead tạo trong kỳ"
                icon={<PhoneCall className="w-5 h-5" />}
                color="amber"
              />
              <KpiCard
                title="SĐT Contact Lại"
                value={recontactPhoneCount.toLocaleString()}
                subtitle="SĐT từ lead cũ tương tác lại"
                icon={<PhoneForwarded className="w-5 h-5" />}
                color="purple"
              />
              <KpiCard
                title="SĐT / Tạo mới"
                value={`${pct(newPhoneCount, newLeadsCount)}%`}
                subtitle={`${newPhoneCount.toLocaleString()} SĐT / ${newLeadsCount.toLocaleString()} lead mới`}
                icon={<Percent className="w-5 h-5" />}
                color="teal"
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
                subtitle="Phân bổ Lead Mới"
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
                    className="text-xs font-semibold text-[#1E5BD6] bg-[#EFF6FF] border border-[#BFDBFE] rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 cursor-pointer shadow-sm hover:bg-[#DBEAFE] transition-colors"
                  >
                    <option value="all">Tổng SĐT{summary ? ` (${summary.phone_leads})` : ''}</option>
                    <option value="new">SĐT Mới{summary ? ` (${summary.new_phone_leads})` : ''}</option>
                    <option value="recontact">SĐT Contact lại{summary ? ` (${summary.recontact_phone_leads})` : ''}</option>
                  </select>
                }
                colorMap={{
                  'Lead Other': '#1E5BD6',
                  'Đào tạo': '#10B981',
                  'Other': '#F59E0B',
                }}
              />
              <StatsPieChart
                title="Tổng Lead / Lead Other & Đào tạo"
                subtitle="Thống kê Tag phân loại (tất cả Lead)"
                stats={summary?.tag_stats}
                colorMap={{
                  'Lead Other': '#1E5BD6',
                  'Đào tạo': '#10B981',
                  'Other': '#F59E0B',
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
