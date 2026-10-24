import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { Users, UserPlus, UserCheck, PhoneCall, PhoneForwarded, Percent, Filter, RefreshCw, LayoutDashboard, Clock, Award, Bot, LogOut, KeyRound, Lock } from 'lucide-react';
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
    <div className="min-h-screen bg-bg-page text-[#111827]">
      {/* Header */}
      <header className="bg-white border-b border-[#E5E7EB] sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <img src="/logo.png" alt="EzTech Logo" className="h-10 object-contain" />
              <div className="ml-2 border-l border-[#E5E7EB] pl-3">
                <h1 className="text-base font-bold text-navy leading-none">Lead Dashboard</h1>
                <p className="text-xs text-[#4B5563] mt-0.5">Pancake Analytics</p>
              </div>
            </div>

            {/* Desktop Navigation Tabs */}
            <div className="hidden sm:flex items-center gap-1 bg-gray-100 p-1 rounded-xl">
              <button
                onClick={() => setActiveTab('overview')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'overview'
                    ? 'bg-white text-navy shadow-sm'
                    : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
                }`}
              >
                <LayoutDashboard className="w-3.5 h-3.5 text-[#1E5BD6]" />
                <span>Tổng quan & Chỉ số</span>
              </button>
              <button
                onClick={() => setActiveTab('remind')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'remind'
                    ? 'bg-white text-navy shadow-sm'
                    : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
                }`}
              >
                <Clock className="w-3.5 h-3.5 text-amber-500" />
                <span>Chăm sóc Lead</span>
              </button>
              <button
                onClick={() => setActiveTab('bot')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'bot'
                    ? 'bg-white text-navy shadow-sm'
                    : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
                }`}
              >
                <Bot className="w-3.5 h-3.5 text-indigo-600" />
                <span>Bot Gửi Tin</span>
              </button>
              <button
                onClick={() => setActiveTab('deals')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'deals'
                    ? 'bg-white text-navy shadow-sm'
                    : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
                }`}
              >
                <Award className="w-3.5 h-3.5 text-[#1E5BD6]" />
                <span>Deal Win</span>
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-[#4B5563]">
                Cập nhật: {format(lastUpdated, 'HH:mm')}
              </span>
            )}
            <button
              onClick={loadData}
              className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-[#4B5563] bg-light-blue/50 hover:bg-light-blue rounded-lg transition-colors border border-transparent hover:border-[#1E5BD6]/20 text-[#1E5BD6]"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Làm mới
            </button>

            {/* User Profile & Actions */}
            {isAuthenticated ? (
              <div className="flex items-center gap-2 pl-2 border-l border-gray-200">
                <div className="flex items-center gap-2 px-2.5 py-1 bg-gray-50 border border-gray-200 rounded-lg">
                  <div className="w-6 h-6 rounded-full bg-indigo-600 text-white text-[11px] font-bold flex items-center justify-center uppercase">
                    {(currentUser?.username || 'A').slice(0, 2)}
                  </div>
                  <div className="hidden md:block text-left">
                    <span className="block text-xs font-bold text-navy leading-none">
                      {currentUser?.username || 'admin'}
                    </span>
                    <span className="text-[10px] text-indigo-600 font-semibold uppercase">
                      {currentUser?.role || 'admin'}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setShowChangePw(true)}
                  title="Đổi mật khẩu"
                  className="p-1.5 text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                >
                  <KeyRound className="w-4 h-4" />
                </button>

                <button
                  type="button"
                  onClick={handleLogout}
                  title="Đăng xuất"
                  className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center pl-2 border-l border-gray-200">
                <button
                  type="button"
                  onClick={() => setActiveTab('bot')}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors border border-indigo-200"
                >
                  <Lock className="w-3.5 h-3.5 text-indigo-600" />
                  <span>Đăng nhập Bot</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Mobile Tab Switcher */}
        <div className="sm:hidden flex items-center gap-1 bg-gray-100 p-1 rounded-xl">
          <button
            onClick={() => setActiveTab('overview')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'overview'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563]'
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5 text-[#1E5BD6]" />
            <span>Tổng quan</span>
          </button>
          <button
            onClick={() => setActiveTab('remind')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'remind'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563]'
            }`}
          >
            <Clock className="w-3.5 h-3.5 text-amber-500" />
            <span>Remind</span>
          </button>
          <button
            onClick={() => setActiveTab('bot')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'bot'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563]'
            }`}
          >
            <Bot className="w-3.5 h-3.5 text-indigo-600" />
            <span>Bot Gửi Tin</span>
          </button>
          <button
            onClick={() => setActiveTab('deals')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'deals'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563]'
            }`}
          >
            <Award className="w-3.5 h-3.5 text-[#1E5BD6]" />
            <span>Deal Win</span>
          </button>
        </div>

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

      <ChangePasswordModal
        isOpen={showChangePw}
        onClose={() => setShowChangePw(false)}
      />
    </div>
  );
}

export default App;
