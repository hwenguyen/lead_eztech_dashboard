import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { Users, UserCheck, PhoneCall, PhoneForwarded, UserX, Filter, RefreshCw } from 'lucide-react';
import { KpiCard } from './components/KpiCard';
import { TrendChart } from './components/TrendChart';
import { LeadTable } from './components/LeadTable';
import { RatioChart } from './components/RatioChart';
import { StatsPieChart } from './components/StatsPieChart';
import { fetchSummary, fetchTrend, fetchLeads, fetchEmployees, fetchPages, type SummaryData, type TrendData, type Lead } from './services/api';

function App() {
  const [startDate, setStartDate] = useState(format(subDays(new Date(), 7), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pageId, setPageId] = useState('');
  const [employee, setEmployee] = useState('');
  const [employeesList, setEmployeesList] = useState<string[]>([]);
  const [pagesList, setPagesList] = useState<string[]>([]);

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const loadFilters = async () => {
      try {
        const empRes = await fetchEmployees();
        setEmployeesList(empRes);
      } catch (error) {
        console.error("Error fetching employees:", error);
      }
      try {
        const pgRes = await fetchPages();
        setPagesList(pgRes);
      } catch (error) {
        console.error("Error fetching pages:", error);
      }
    };
    loadFilters();
  }, []);

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
  const contactedLeadsCount = summary?.contacted_leads || 0;
  const newPhoneCount = summary?.new_phone_leads || 0;
  const recontactPhoneCount = summary?.recontact_phone_leads || 0;
  const uncontactedCount = summary?.uncontacted_new_leads ?? (newLeadsCount > contactedLeadsCount ? newLeadsCount - contactedLeadsCount : 0);

  const rateContact = newLeadsCount > 0 ? (contactedLeadsCount / newLeadsCount) * 100 : 0;
  const rateNewPhone = newLeadsCount > 0 ? (newPhoneCount / newLeadsCount) * 100 : 0;

  return (
    <div className="min-h-screen bg-bg-page text-[#111827]">
      {/* Header */}
      <header className="bg-white border-b border-[#E5E7EB] sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="EzTech Logo" className="h-10 object-contain" />
            <div className="ml-2 border-l border-[#E5E7EB] pl-3">
              <h1 className="text-base font-bold text-navy leading-none">Lead Dashboard</h1>
              <p className="text-xs text-[#4B5563] mt-0.5">Pancake Analytics</p>
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
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

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
                <label className="text-xs font-medium text-[#4B5563]">Page ID</label>
                <select
                  value={pageId}
                  onChange={e => setPageId(e.target.value)}
                  className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827] cursor-pointer"
                >
                  <option value="">Tất cả Page</option>
                  {pagesList.map(pg => (
                    <option key={pg} value={pg}>{pg}</option>
                  ))}
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
            {/* KPIs row - 5 cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              <KpiCard
                title="Lead Mới"
                value={newLeadsCount.toLocaleString()}
                subtitle="Khách mới trong kỳ"
                icon={<Users className="w-5 h-5" />}
                color="blue"
              />
              <KpiCard
                title="Lead Liên Hệ"
                value={contactedLeadsCount.toLocaleString()}
                subtitle={`${rateContact.toFixed(1)}% tỉ lệ liên hệ`}
                icon={<UserCheck className="w-5 h-5" />}
                color="green"
              />
              <KpiCard
                title="SĐT Mới"
                value={newPhoneCount.toLocaleString()}
                subtitle={`${rateNewPhone.toFixed(1)}% tỉ lệ SĐT mới`}
                icon={<PhoneCall className="w-5 h-5" />}
                color="amber"
              />
              <KpiCard
                title="SĐT Liên Hệ Lại"
                value={recontactPhoneCount.toLocaleString()}
                subtitle="Khách cũ tương tác lại"
                icon={<PhoneForwarded className="w-5 h-5" />}
                color="indigo"
              />
              <KpiCard
                title="Chưa Liên Hệ"
                value={uncontactedCount.toLocaleString()}
                subtitle="Lead mới cần follow up"
                icon={<UserX className="w-5 h-5" />}
                color="rose"
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
                  contactedLeads={contactedLeadsCount}
                  phoneLeads={summary?.phone_leads || (newPhoneCount + recontactPhoneCount)}
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
