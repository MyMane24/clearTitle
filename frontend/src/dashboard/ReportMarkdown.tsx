import React from 'react';

import { emphasisPattern, parseReportBlocks, reportSections } from './transactionResults';

function renderEmphasis(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(emphasisPattern)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const key = `${keyPrefix}-${index++}`;
    if (match[1] !== undefined) nodes.push(<strong key={key}>{match[1]}</strong>);
    else if (match[2] !== undefined) nodes.push(<code key={key}>{match[2]}</code>);
    else nodes.push(<em key={key}>{match[3] ?? match[4]}</em>);
    cursor = start + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function Blocks({ body, prefix }: { body: string; prefix: string }) {
  return (
    <>
      {parseReportBlocks(body).map((block, index) => {
        const key = `${prefix}-${index}`;
        switch (block.kind) {
          case 'subheading':
            return <h6 key={key} className="report-md-subheading">{renderEmphasis(block.text, key)}</h6>;
          case 'bullets':
            return (
              <ul key={key} className="report-md-list">
                {block.items.map((item, i) => <li key={i}>{renderEmphasis(item, `${key}-${i}`)}</li>)}
              </ul>
            );
          case 'numbered':
            return (
              <ol key={key} className="report-md-list">
                {block.items.map((item, i) => <li key={i}>{renderEmphasis(item, `${key}-${i}`)}</li>)}
              </ol>
            );
          case 'quote':
            return <blockquote key={key} className="report-md-quote">{renderEmphasis(block.text, key)}</blockquote>;
          case 'table':
            return (
              <div key={key} className="report-md-table-wrap">
                <table className="report-md-table">
                  <thead>
                    <tr>{block.header.map((cell, c) => <th key={c}>{renderEmphasis(cell, `${key}-h${c}`)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={r}>
                        {block.header.map((_, c) => <td key={c}>{renderEmphasis(row[c] ?? '', `${key}-${r}-${c}`)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return <p key={key} className="report-md-paragraph">{renderEmphasis(block.text, key)}</p>;
        }
      })}
    </>
  );
}

/** Renders the report narrative: `##` sections with headings, then bullets, steps, tables and quotes. */
export function ReportMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="report-md">
      {reportSections(markdown).map((section, index) => (
        <div className="report-md-section" key={index}>
          {section.heading ? <h5 className="report-md-heading">{renderEmphasis(section.heading, `s${index}`)}</h5> : null}
          <Blocks body={section.body} prefix={`b${index}`} />
        </div>
      ))}
    </div>
  );
}
