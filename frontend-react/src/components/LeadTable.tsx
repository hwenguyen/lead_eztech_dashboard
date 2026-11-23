import React, { useState } from 'react';
import type { Lead } from '../services/api';
import { Phone, MessageSquare, User, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react';
import { safeFormatDate, toSafeHttpUrl } from '../utils/format';

interface LeadTableProps {
  leads: Lead[];
  totalLeads: number;
  page: number;
  pageSize: number;
  loadingPage?: boolean;
  onPageChange: (page: number) => void;
}

function extractLastReadableMessage(raw?: string): string {
  if (!raw) return '';
  const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    const cleaned = lines[i].replace(/^\[.*?\]:\s*/, '').trim();
    if (cleaned) return cleaned;
  }
  return '';
}

export const LeadTable = React.memo(function LeadTable({
  leads,
  totalLeads,
  page,
  pageSize,
  loadingPage = false,
  onPageChange,
}: LeadTableProps) {
  const totalPages = Math.max(1, Math.ceil(totalLeads / pageSize));
  const [expandedMsgIds, setExpandedMsgIds] = useState<Set<number>>(new Set());

  const toggleExpandMsg = (id: number) => {
    setExpandedMsgIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden flex flex-col">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-baseline gap-2.5">
          <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">Danh sách Lead</h3>
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-mono font-medium bg-slate-100 text-slate-600 tabular-nums">
            {totalLeads.toLocaleString()} khách hàng
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[13px] text-left">
          <thead>
            <tr className="text-[11px] font-semibold text-slate-400 bg-slate-50/70 border-b border-slate-100 uppercase tracking-[0.06em]">
              <th scope="col" className="px-5 py-3 min-w-[210px]">Khách Hàng</th>
              <th scope="col" className="px-5 py-3 whitespace-nowrap">Nhân Viên</th>
              <th scope="col" className="px-5 py-3 whitespace-nowrap">Số Điện Thoại</th>
              <th scope="col" className="px-5 py-3">Phân Loại (Tags)</th>
              <th scope="col" className="px-5 py-3 whitespace-nowrap">Trạng Thái</th>
              <th scope="col" className="px-5 py-3 w-full min-w-[280px]">Tin Nhắn Gần Nhất</th>
            </tr>
          </thead>
          <tbody className={`divide-y divide-slate-100 transition-opacity ${loadingPage ? 'opacity-60' : ''}`}>
            {leads.length > 0 ? leads.map((lead) => {
              const cleanMsg = extractLastReadableMessage(lead.messages);
              const safePancakeUrl = toSafeHttpUrl(lead.pancake_url);
              const safePostUrl = toSafeHttpUrl(lead.post_url);
              const assignedList = (lead.assigned_users || '')
                .split(',')
                .map((u) => u.trim())
                .filter(Boolean);
              const tagList = (lead.status_tag || '')
                .split(',')
                .map((t) => t.trim())
                .filter(Boolean);
              const isExpanded = expandedMsgIds.has(lead.id);

              return (
                <tr key={lead.id} className="hover:bg-slate-50/70 transition-colors group">
                  {/* Khách hàng */}
                  <td className="px-5 py-3.5 align-top">
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 mt-0.5 rounded-lg bg-eztech-light border border-eztech-border/70 flex items-center justify-center text-eztech text-xs font-bold shrink-0">
                        {(lead.name || 'K').charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="font-semibold text-navy leading-snug">{lead.name || 'Khách từ CRM'}</div>
                        <div className="text-[11px] font-mono text-slate-400 mt-0.5 tabular-nums">
                          {safeFormatDate(lead.first_created_at, 'dd/MM/yyyy HH:mm')}
                        </div>
                        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                          {lead.is_new ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-emerald-50/80 text-emerald-700 border border-emerald-200/60">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                              Tạo mới
                            </span>
                          ) : null}
                          {!lead.is_new && lead.is_contacted ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-eztech-light text-eztech border border-eztech-border/60">
                              <span className="w-1.5 h-1.5 rounded-full bg-eztech" />
                              Tương tác lại
                            </span>
                          ) : null}
                          {safePancakeUrl && (
                            <a
                              href={safePancakeUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-600 hover:text-eztech bg-white hover:bg-eztech-light px-1.5 py-0.5 rounded-md border border-slate-200 hover:border-eztech-border transition-colors"
                              title={`Mở Pancake: ${safePancakeUrl}`}
                            >
                              <ExternalLink className="w-2.5 h-2.5" aria-hidden="true" />
                              <span>Pancake</span>
                            </a>
                          )}
                          {safePostUrl ? (
                            <a
                              href={safePostUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[10px] font-medium text-indigo-600 hover:text-indigo-800 bg-indigo-50/90 hover:bg-indigo-100 px-1.5 py-0.5 rounded-md border border-indigo-200/80 hover:border-indigo-300 transition-colors"
                              title={lead.post_id ? `Mở bài viết / video (Post ID: ${lead.post_id})` : 'Mở bài viết / video'}
                            >
                              <ExternalLink className="w-2.5 h-2.5" aria-hidden="true" />
                              <span>Post</span>
                            </a>
                          ) : lead.post_id ? (
                            <span
                              className="inline-flex items-center gap-1 text-[10px] font-medium text-indigo-600 bg-indigo-50/90 px-1.5 py-0.5 rounded-md border border-indigo-200/80"
                              title={`Post ID: ${lead.post_id}`}
                            >
                              <span>Post</span>
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Nhân viên */}
                  <td className="px-5 py-3.5 align-top whitespace-nowrap">
                    {assignedList.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {assignedList.map((name, i) => {
                          const isUnassigned = name.toLowerCase().includes('chưa phân') || name === '—';
                          return (
                            <span
                              key={`${name}-${i}`}
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap ${
                                isUnassigned
                                  ? 'bg-slate-50 text-slate-500 border border-slate-200/80'
                                  : 'bg-eztech-light/70 text-navy border border-eztech-border/60'
                              }`}
                            >
                              <User className={`w-3 h-3 shrink-0 ${isUnassigned ? 'text-slate-400' : 'text-eztech'}`} aria-hidden="true" />
                              <span>{name}</span>
                            </span>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-50 text-slate-500 border border-slate-200/80 whitespace-nowrap">
                        <User className="w-3 h-3 text-slate-400 shrink-0" aria-hidden="true" />
                        <span>Chưa phân công</span>
                      </span>
                    )}
                  </td>

                  {/* SĐT */}
                  <td className="px-5 py-3.5 align-top whitespace-nowrap">
                    {lead.phone_number ? (
                      <a
                        href={`tel:${lead.phone_number.replace(/[^\d+]/g, '')}`}
                        className="inline-flex items-center gap-1.5 font-mono text-xs font-medium text-eztech hover:text-navy bg-eztech-light/50 hover:bg-eztech-light px-2 py-1 rounded-md border border-eztech-border/50 transition-colors tabular-nums"
                      >
                        <Phone className="w-3 h-3" aria-hidden="true" />
                        {lead.phone_number}
                      </a>
                    ) : (
                      <span className="text-slate-400 text-xs">—</span>
                    )}
                  </td>

                  {/* Tags */}
                  <td className="px-5 py-3.5 align-top">
                    {tagList.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {tagList.map((tagTrimmed, i) => {
                          const event = lead.tag_timeline?.find(
                            (t) => t.tag.trim().toLowerCase() === tagTrimmed.toLowerCase()
                          );
                          const formattedTime = event?.tagged_at ? safeFormatDate(event.tagged_at, 'dd/MM HH:mm', '') : '';
                          const fullTimeStr = event?.tagged_at ? safeFormatDate(event.tagged_at, 'dd/MM/yyyy HH:mm', '') : '';
                          const tooltip = fullTimeStr
                            ? `Gắn lúc: ${fullTimeStr}${event?.editor ? ` bởi ${event.editor}` : ''}`
                            : tagTrimmed;

                          return (
                            <span
                              key={`${tagTrimmed}-${i}`}
                              title={tooltip}
                              className="inline-flex flex-col px-2 py-0.5 rounded-md text-xs font-medium bg-slate-50 text-slate-700 border border-slate-200/80 whitespace-nowrap cursor-help hover:border-eztech/40 hover:bg-eztech-light/30 transition-colors"
                            >
                              <span className="flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-gold shrink-0" />
                                <span>{tagTrimmed}</span>
                              </span>
                              {formattedTime && (
                                <span className="text-[10px] font-mono text-slate-400 font-normal leading-tight pl-3 tabular-nums">
                                  {formattedTime}
                                </span>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-slate-400 text-xs">—</span>
                    )}
                  </td>

                  {/* Liên hệ */}
                  <td className="px-5 py-3.5 align-top whitespace-nowrap">
                    {lead.is_contacted ? (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50/70 text-emerald-700 border border-emerald-200/60 whitespace-nowrap">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        Đã LH
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium bg-slate-50 text-slate-500 border border-slate-200/80 whitespace-nowrap">
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                        Chưa LH
                      </span>
                    )}
                  </td>

                  {/* Tin nhắn */}
                  <td className="px-5 py-3.5 align-top">
                    {cleanMsg ? (
                      <button
                        type="button"
                        onClick={() => toggleExpandMsg(lead.id)}
                        title={isExpanded ? 'Thu gọn tin nhắn' : 'Nhấn để xem đầy đủ tin nhắn'}
                        className="flex items-start gap-2 text-left w-full cursor-pointer group/msg"
                      >
                        <MessageSquare className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" aria-hidden="true" />
                        <p className={`text-slate-600 text-xs leading-relaxed whitespace-pre-wrap ${isExpanded ? '' : 'line-clamp-2'}`}>
                          {cleanMsg}
                        </p>
                      </button>
                    ) : (
                      <span className="text-slate-400 text-xs italic">Không có tin nhắn</span>
                    )}
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center">
                  <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-slate-100 mb-2">
                    <User className="w-4 h-4 text-slate-400" aria-hidden="true" />
                  </div>
                  <p className="text-xs text-slate-500">Không có khách hàng nào trong khoảng thời gian này</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {totalLeads > pageSize && (
        <div className="px-5 py-3.5 border-t border-slate-100 flex items-center justify-between bg-slate-50/50">
          <span className="text-xs text-slate-500 tabular-nums">
            Hiển thị <span className="font-mono font-semibold text-navy">{(page - 1) * pageSize + 1}</span>–<span className="font-mono font-semibold text-navy">{Math.min(page * pageSize, totalLeads)}</span> / <span className="font-mono font-semibold text-navy">{totalLeads.toLocaleString()}</span>
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1 || loadingPage}
              aria-label="Trang trước"
              className="p-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:border-eztech/40 hover:text-eztech disabled:opacity-40 disabled:pointer-events-none transition-colors cursor-pointer"
            >
              <ChevronLeft className="w-4 h-4" aria-hidden="true" />
            </button>
            <span className="text-xs font-mono font-medium text-slate-600 px-2.5 tabular-nums">
              {page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages || loadingPage}
              aria-label="Trang sau"
              className="p-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:border-eztech/40 hover:text-eztech disabled:opacity-40 disabled:pointer-events-none transition-colors cursor-pointer"
            >
              <ChevronRight className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
