import type { ConflictEvent, DatasetSummary, TimelinePoint, WeiboPost } from '../types';
import { formatBarWidth, formatDatasetLabel } from '../lib/format';

type Props = {
  summaries: DatasetSummary[];
  timeline: TimelinePoint[];
  events: ConflictEvent[];
  posts: WeiboPost[];
  maxTimelineValue: number;
};

export function OverviewTab({ summaries, timeline, events, posts, maxTimelineValue }: Props) {
  return (
    <div className="overview-layout">
      <section className="panel">
        <div className="panel-header">
          <h2>数据资源概览</h2>
          <span>Data Lake</span>
        </div>
        <div className="summary-grid">
          {summaries.map((item) => (
            <article key={item.dataset} className="summary-card">
              <h3>{formatDatasetLabel(item.dataset)}</h3>
              <p className="metric">{item.total_rows.toLocaleString()}</p>
              <p className="muted">条记录</p>
              <div className="chips">
                {item.columns.slice(0, 6).map((column) => (
                  <span key={column} className="chip">
                    {column}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel panel-span-2">
        <div className="panel-header">
          <h2>冲突事件时间线</h2>
          <span>ACLED Timeline</span>
        </div>
        <div className="timeline-list compact-timeline">
          {timeline.slice(0, 24).map((point) => (
            <div key={point.date} className="timeline-row">
              <div className="timeline-meta">
                <strong>{point.date}</strong>
                <span>{point.value} events</span>
              </div>
              <div className="timeline-bar-wrap">
                <div className="timeline-bar" style={{ width: formatBarWidth(point.value, maxTimelineValue) }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>冲突事件样本</h2>
          <span>Events</span>
        </div>
        <div className="card-list scroll-list">
          {events.map((event) => (
            <article key={event.event_id_cnty} className="feed-card">
              <div className="feed-topline">
                <strong>{event.event_type || 'Unknown'}</strong>
                <span>{event.event_date}</span>
              </div>
              <p className="feed-title">
                {event.location || 'Unknown'} · {event.admin1 || '-'}
              </p>
              <p className="feed-body">
                {event.actor1 || '-'}
                {event.actor2 ? ` vs ${event.actor2}` : ''}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>微博舆情样本</h2>
          <span>Weibo</span>
        </div>
        <div className="card-list scroll-list">
          {posts.map((post) => (
            <article key={`${post.index}-${post.created_at}`} className="feed-card">
              <div className="feed-topline">
                <strong>{post.screen_name || 'Unknown'}</strong>
                <span>{post.created_at || ''}</span>
              </div>
              <p className="feed-body clamp-4">{post.text || ''}</p>
              <p className="feed-meta">
                {post.source || '-'} · 赞 {post.attitudes_count ?? 0}
              </p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
