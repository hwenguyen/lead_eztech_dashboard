
import type { Lead } from '../services/api';
import { format } from 'date-fns';
import { Phone, MessageSquare, User, CheckCircle, XCircle } from 'lucide-react';

interface LeadTableProps {
  leads: Lead[];
}

export function LeadTable({ leads }: LeadTableProps) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Danh sách Lead</h3>
          <p className="text-xs text-gray-400 mt-0.5">Tổng {leads.length} khách hàng</p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-gray-400 bg-gray-50 uppercase tracking-wide">
              <th className="px-6 py-3 font-medium">Khách Hàng</th>
              <th className="px-6 py-3 font-medium">Nhân Viên</th>
              <th className="px-6 py-3 font-medium">SĐT</th>
              <th className="px-6 py-3 font-medium">Tags</th>
              <th className="px-6 py-3 font-medium">Liên Hệ</th>
              <th className="px-6 py-3 font-medium w-full">Tin Nhắn Gần Nhất</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {leads.length > 0 ? leads.map((lead) => {
              // Lấy dòng tin nhắn cuối cùng từ khách hàng
              const msgLines = (lead.messages || '').split('\n').filter(Boolean);
              const lastMsg = msgLines[msgLines.length - 1] || '';
              // Cắt bớt prefix [Sender]:
              const cleanMsg = lastMsg.replace(/^\[.*?\]:\s*/, '');

              return (
                <tr key={lead.id} className="hover:bg-gray-50/60 transition-colors group">
                  {/* Khách hàng */}
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
                        {(lead.name || 'K').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="font-medium text-gray-900">{lead.name || 'Khách từ CRM'}</div>
                        <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-1">
                          {format(new Date(lead.first_created_at), 'dd/MM/yyyy HH:mm')}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Nhân viên */}
                  <td className="px-6 py-4">
                    {lead.assigned_users ? (
                      <div className="flex flex-wrap gap-1">
                        {lead.assigned_users.split(',').map((u, i) => (
                          <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                            <User className="w-3 h-3" />
                            {u.trim()}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-300 text-xs">Chưa phân</span>
                    )}
                  </td>

                  {/* SĐT */}
                  <td className="px-6 py-4">
                    {lead.phone_number ? (
                      <a href={`tel:${lead.phone_number}`} className="inline-flex items-center gap-1.5 text-blue-600 font-medium hover:text-blue-800 transition-colors">
                        <Phone className="w-3.5 h-3.5" />
                        {lead.phone_number}
                      </a>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>

                  {/* Tags */}
                  <td className="px-6 py-4">
                    {lead.status_tag ? (
                      <div className="flex flex-wrap gap-1">
                        {lead.status_tag.split(',').map((tag, i) => (
                          <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-100">
                            {tag.trim()}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>

                  {/* Liên hệ */}
                  <td className="px-6 py-4">
                    {lead.is_contacted ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-100">
                        <CheckCircle className="w-3 h-3" /> Đã LH
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-50 text-gray-400 border border-gray-100">
                        <XCircle className="w-3 h-3" /> Chưa LH
      </span>
                    )}
                  </td>

                  {/* Tin nhắn */}
                  <td className="px-6 py-4 max-w-[320px]">
                    {cleanMsg ? (
                      <div className="flex items-start gap-2">
                        <MessageSquare className="w-3.5 h-3.5 text-gray-300 mt-0.5 shrink-0" />
                        <p className="text-gray-600 text-xs line-clamp-2">{cleanMsg}</p>
                      </div>
                    ) : (
                      <span className="text-gray-300 text-xs italic">Không có tin nhắn</span>
                    )}
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} className="px-6 py-20 text-center">
                  <div className="flex flex-col items-center gap-3 text-gray-300">
                    <MessageSquare className="w-10 h-10" />
                    <p className="text-sm font-medium">Không có dữ liệu</p>
                    <p className="text-xs">Hãy thử thay đổi bộ lọc thời gian</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
