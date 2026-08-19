import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { LayoutDashboard, Users, UserCheck, PhoneCall, Filter, RefreshCw } from 'lucide-react';
import { KpiCard } from './components/KpiCard';
import { TrendChart } from './components/TrendChart';
import { LeadTable } from './components/LeadTable';
import { RatioChart } from './components/RatioChart';
import { StatsPieChart } from './components/StatsPieChart';
import { fetchSummary, fetchTrend, fetchLeads, fetchEmployees, type SummaryData, type TrendData, type Lead } from './services/api';

function App() {
  const [startDate, setStartDate] = useState(format(subDays(new Date(), 7), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pageId, setPageId] = useState('');
  const [employee, setEmployee] = useState('');
  const [employeesList, setEmployeesList] = useState<string[]>([]);

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const loadEmployees = async () => {
      try {
        const empRes = await fetchEmployees();
        setEmployeesList(empRes);
      } catch (error) {
        console.error("Error fetching employees:", error);
      }
    };
    loadEmployees();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [sumRes, trRes, ldRes] = await Promise.all([
        fetchSummary(startDate, endDate, pageId, employee),
        fetchTrend(startDate, endDate, pageId, employee),
        fetchLeads(pageId, employee, startDate, endDate, 1, pageSize)
      ]);
      setSummary(sumRes);
      setTrend(trRes);
      setLeads(ldRes.data);
      setTotalLeads(ldRes.total);
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

  const rateContact = summary?.new_leads ? (summary.contacted_leads / summary.new_leads) * 100 : 0;
  const ratePhone = summary?.new_leads ? (summary.phone_leads / summary.new_leads) * 100 : 0;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-blue-600 rounded-xl flex items-center justify-center shadow-sm">
              <LayoutDashboard className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-900 leading-none">EzTech Lead Dashboard</h1>
              <p className="text-xs text-gray-400 mt-0.5">Pancake Analytics</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-gray-400">
                Cập nhật: {format(lastUpdated, 'HH:mm')}
              </span>
            )}
            <button
              onClick={loadData}
              className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Làm mới
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {/* Filter Panel */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="w-4 h-4 text-gray-400" />
            <span className="text-sm font-semibold text-gray-700">Bộ lọc</span>
          </div>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-400">Từ ngày</label>
              <input
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-400">Đến ngày</label>
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
              />
            </div>
            <div className="h-9 w-px bg-gray-200 mx-1" />
            <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
              <label className="text-xs font-medium text-gray-400">Page ID</label>
              <input
                type="text"
                placeholder="Tất cả Page..."
                value={pageId}
                onChange={e => setPageId(e.target.value)}
                className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all w-full"
              />
            </div>
            <div className="flex flex-col gap-1 min-w-[200px]">
              <label className="text-xs font-medium text-gray-400">Nhân Viên</label>
              <select
                value={employee}
                onChange={e => setEmployee(e.target.value)}
                className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
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
            {/* KPIs row */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard
                title="Lead Mới"
                value={summary?.new_leads?.toLocaleString() || '0'}
                subtitle="Khách hàng mới trong kỳ"
                icon={<Users className="w-5 h-5" />}
                color="blue"
              />
              <KpiCard
                title="Lead Liên Hệ"
                value={summary?.contacted_leads?.toLocaleString() || '0'}
                subtitle={`${rateContact.toFixed(1)}% tỉ lệ contact`}
                icon={<UserCheck className="w-5 h-5" />}
                color="green"
              />
              <KpiCard
                title="Lead Có SĐT"
                value={summary?.phone_leads?.toLocaleString() || '0'}
                subtitle={`${ratePhone.toFixed(1)}% tỉ lệ để lại SĐT`}
                icon={<PhoneCall className="w-5 h-5" />}
                color="amber"
              />
              <KpiCard
                title="Chưa Liên Hệ"
                value={summary ? (summary.new_leads - summary.contacted_leads).toLocaleString() : '0'}
                subtitle="Cần follow up"
                icon={<Users className="w-5 h-5" />}
                color="purple"
              />
            </div>

            {/* Charts row */}
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
              <div className="lg:col-span-3">
                <TrendChart data={trend} />
              </div>
              <div className="lg:col-span-1">
                <RatioChart
                  newLeads={summary?.new_leads || 0}
                  contactedLeads={summary?.contacted_leads || 0}
                  phoneLeads={summary?.phone_leads || 0}
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
                title="Lead Có SĐT / Nhân viên"
                subtitle="Phân bổ Lead Có SĐT"
                stats={summary?.phone_leads_employee_stats}
              />
              <StatsPieChart
                title="Lead theo Khoá học"
                subtitle="Thống kê Tag quan tâm"
                stats={summary?.tag_stats}
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
      </main>
    </div>
  );
}

export default App;
