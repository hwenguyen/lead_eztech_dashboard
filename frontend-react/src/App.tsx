import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { LayoutDashboard, Users, UserCheck, PhoneCall } from 'lucide-react';
import { KpiCard } from './components/KpiCard';
import { TrendChart } from './components/TrendChart';
import { LeadTable } from './components/LeadTable';
import { fetchSummary, fetchTrend, fetchLeads, type SummaryData, type TrendData, type Lead } from './services/api';

function App() {
  const [startDate, setStartDate] = useState(format(subDays(new Date(), 7), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pageId, setPageId] = useState('');

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const [sumRes, trRes, ldRes] = await Promise.all([
          fetchSummary(startDate, endDate, pageId),
          fetchTrend(startDate, endDate, pageId),
          fetchLeads(pageId)
        ]);
        setSummary(sumRes);
        setTrend(trRes);
        setLeads(ldRes.data);
      } catch (error) {
        console.error("Error fetching data:", error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [startDate, endDate, pageId]);

  const rateContact = summary?.new_leads ? (summary.contacted_leads / summary.new_leads) * 100 : 0;
  const ratePhone = summary?.new_leads ? (summary.phone_leads / summary.new_leads) * 100 : 0;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="bg-card border-b border-border sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 p-2 rounded-lg">
              <LayoutDashboard className="w-6 h-6 text-primary" />
            </div>
            <h1 className="text-xl font-semibold text-foreground tracking-tight">Pancake Lead Dashboard</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Filters */}
        <div className="bg-card p-4 rounded-xl border border-border shadow-sm flex flex-wrap gap-4 items-end">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">Từ ngày</label>
            <input 
              type="date" 
              value={startDate} 
              onChange={e => setStartDate(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">Đến ngày</label>
            <input 
              type="date" 
              value={endDate} 
              onChange={e => setEndDate(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
            />
          </div>
          <div className="flex flex-col gap-1.5 flex-1 min-w-[200px]">
            <label className="text-xs font-medium text-muted-foreground">Page ID (Bỏ trống để xem tất cả)</label>
            <input 
              type="text" 
              placeholder="Nhập Page ID..."
              value={pageId} 
              onChange={e => setPageId(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all w-full"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        ) : (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <KpiCard 
                title="Lead Mới" 
                value={summary?.new_leads?.toLocaleString() || '0'} 
                icon={<Users className="w-5 h-5" />}
              />
              <KpiCard 
                title="Lead Liên Hệ" 
                value={summary?.contacted_leads?.toLocaleString() || '0'} 
                subtitle={`${rateContact.toFixed(1)}% tỉ lệ contact`}
                icon={<UserCheck className="w-5 h-5" />}
              />
              <KpiCard 
                title="Lead Có SĐT" 
                value={summary?.phone_leads?.toLocaleString() || '0'} 
                subtitle={`${ratePhone.toFixed(1)}% tỉ lệ để lại SĐT`}
                icon={<PhoneCall className="w-5 h-5" />}
              />
            </div>

            {/* Chart */}
            <TrendChart data={trend} />

            {/* Table */}
            <LeadTable leads={leads} />
          </>
        )}

      </main>
    </div>
  );
}

export default App;
