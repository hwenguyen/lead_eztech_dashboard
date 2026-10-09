import type { Lead } from '../services/api';
import { format } from 'date-fns';
import { Phone, MessageSquare, User, CheckCircle, XCircle, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react';

interface LeadTableProps {
  leads: Lead[];
  totalLeads: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function LeadTable({ leads, totalLeads, page, pageSize, onPageChange }: LeadTableProps) {
  const totalPages = Math.ceil(totalLeads / pageSize);

  return (
    <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm overflow-hidden flex flex-col">
      <div className="px-6 py-4 border-b border-[#E5E7EB] flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-navy">Danh sách Lead</h3>
          <p className="text-xs text-[#4B5563] mt-0.5">Tổng {totalLeads} khách hàng</p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-[#4B5563] bg-[#F3F6FA] uppercase tracking-wide">
              <th className="px-6 py-3 font-medium">Khách Hàng</th>
              <th className="px-6 py-3 font-medium">Nhân Viên</th>
              <th className="px-6 py-3 font-medium">SĐT</th>
              <th className="px-6 py-3 font-medium">Tags</th>
              <th className="px-6 py-3 font-medium">Liên Hệ</th>
              <th className="px-6 py-3 font-medium w-full min-w-[300px]">Tin Nhắn Gần Nhất</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E5E7EB]">
            {leads.length > 0 ? leads.map((lead) => {
              // Lấy dòng tin nhắn cuối cùng từ khách hàng
              const msgLines = (lead.messages || '').split('\n').filter(Boolean);
              const lastMsg = msgLines[msgLines.length - 1] || '';
              // Cắt bớt prefix [Sender]:
              const cleanMsg = lastMsg.replace(/^\[.*?\]:\s*/, '');

              return (
                <tr key={lead.id} className="hover:bg-[#F3F6FA] transition-colors group">
                  {/* Khách hàng */}
                  <td className="px-6 py-4 align-top">
                    <div className="flex items-start gap-3">
                      <div className="w-9 h-9 mt-0.5 rounded-full bg-gradient-to-br from-navy to-eztech flex items-center justify-center text-white text-xs font-bold shrink-0">
                        {(lead.name || 'K').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-navy">{lead.name || 'Khách từ CRM'}</span>
                          {lead.pancake_url && (
                            <a
                              href={lead.pancake_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[11px] font-medium text-eztech hover:text-navy bg-light-blue/80 hover:bg-light-blue px-1.5 py-0.5 rounded border border-eztech/20 transition-colors"
                              title={`Mở Pancake: ${lead.pancake_url}`}
                            >
                              <ExternalLink className="w-2.5 h-2.5" />
                              <span>Pancake</span>
                            </a>
                          )}
                        </div>
                        <div className="text-xs text-[#4B5563] mt-0.5 flex flex-col gap-1">
                          <span className="text-[#6B7280]">{lead.first_created_at ? format(new Date(lead.first_created_at), 'dd/MM/yyyy HH:mm') : '—'}</span>
                          <div className="flex gap-1 mt-1">
                            {lead.is_new ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-800 border border-green-200">
                                Tạo mới
                              </span>
                            ) : null}
                            {!lead.is_new && lead.is_contacted ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 border border-blue-200">
                                Tương tác lại
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Nhân viên */}
                  <td className="px-6 py-4 align-top">
                    {lead.assigned_users ? (
                      <div className="flex flex-wrap gap-1">
                        {lead.assigned_users.split(',').map((u, i) => (
                          <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-light-blue text-eztech border border-eztech/20">
                            <User className="w-3 h-3" />
                            {u.trim()}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[#4B5563] text-xs">Chưa phân</span>
                    )}
                  </td>

                  {/* SĐT */}
                  <td className="px-6 py-4 align-top">
                    {lead.phone_number ? (
                      <a href={`tel:${lead.phone_number}`} className="inline-flex items-center gap-1.5 text-eztech font-medium hover:text-navy transition-colors">
                        <Phone className="w-3.5 h-3.5" />
                        {lead.phone_number}
                      </a>
                    ) : (
                      <span className="text-[#4B5563] text-xs">—</span>
                    )}
                  </td>

                  {/* Tags */}
                  <td className="px-6 py-4 align-top">
                    {lead.status_tag ? (
                      <div className="flex flex-wrap gap-1.5">
                        {lead.status_tag.split(',').map((tag, i) => {
                          const tagTrimmed = tag.trim();
                          const event = lead.tag_timeline?.find(
                            t => t.tag.trim().toLowerCase() === tagTrimmed.toLowerCase()
                          );
                          let formattedTime: string | null = null;
                          let fullTimeStr: string | null = null;
                          if (event?.tagged_at) {
                            try {
                              const d = new Date(event.tagged_at);
                              if (!isNaN(d.getTime())) {
                                formattedTime = format(d, 'dd/MM HH:mm');
                                fullTimeStr = format(d, 'dd/MM/yyyy HH:mm');
                              }
                            } catch (_) {}
                          }
                          const tooltip = fullTimeStr
                            ? `Gắn lúc: ${fullTimeStr}${event?.editor ? ` bởi ${event.editor}` : ''}`
                            : tagTrimmed;

                          return (
                            <span
                              key={i}
                              title={tooltip}
                              className="inline-flex flex-col px-2 py-0.5 rounded-lg text-xs font-medium bg-purple-50 text-purple-700 border border-purple-100 whitespace-nowrap cursor-help hover:bg-purple-100 transition-colors"
                            >
                              <span>{tagTrimmed}</span>
                              {formattedTime && (
                                <span className="text-[10px] text-purple-400 font-normal leading-tight">
                                  {formattedTime}
                                </span>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-[#4B5563] text-xs">—</span>
                    )}
                  </td>

                  {/* Liên hệ */}
                  <td className="px-6 py-4 align-top">
                    {lead.is_contacted ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-[#10B981] border border-[#10B981]/20 whitespace-nowrap">
                        <CheckCircle className="w-3 h-3" /> Đã LH
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#F3F6FA] text-[#4B5563] border border-[#E5E7EB] whitespace-nowrap">
                        <XCircle className="w-3 h-3" /> Chưa LH
                      </span>
                    )}
                  </td>

                  {/* Tin nhắn */}
                  <td className="px-6 py-4 align-top">
                    {cleanMsg ? (
                      <div className="flex items-start gap-2">
                        <MessageSquare className="w-3.5 h-3.5 text-[#4B5563] mt-0.5 shrink-0" />
                        <p className="text-[#4B5563] text-xs leading-relaxed whitespace-pre-wrap">{cleanMsg}</p>
                      </div>
                    ) : (
                      <span className="text-[#4B5563] text-xs italic">Không có tin nhắn</span>
                    )}
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center">
                  <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[#F3F6FA] mb-3">
                    <User className="w-5 h-5 text-[#4B5563]" />
                  </div>
                  <p className="text-sm text-[#4B5563]">Không có khách hàng nào</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="px-6 py-4 border-t border-[#E5E7EB] flex items-center justify-between bg-[#F3F6FA]">
          <span className="text-xs text-[#4B5563]">
            Hiển thị <span className="font-medium text-navy">{(page - 1) * pageSize + 1}</span> - <span className="font-medium text-navy">{Math.min(page * pageSize, totalLeads)}</span> trong <span className="font-medium text-navy">{totalLeads}</span> khách hàng
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              className="p-1.5 rounded-lg border border-[#E5E7EB] text-[#4B5563] hover:bg-white hover:text-eztech disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-[#4B5563] transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs font-medium text-[#4B5563] px-2">Trang {page} / {totalPages}</span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="p-1.5 rounded-lg border border-[#E5E7EB] text-[#4B5563] hover:bg-white hover:text-eztech disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-[#4B5563] transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
