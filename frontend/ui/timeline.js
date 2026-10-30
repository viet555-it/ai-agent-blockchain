import { t } from '../i18n.js';
import { icons } from '../icons.js';
import { escapeHtml } from './format.js';

export function createTimelineView(state, elements) {
  function renderTimeline(timelineSteps) {
    if (!timelineSteps || timelineSteps.length === 0) {
      state.lastTimelineSteps = null;
      elements.timelineEmptyState.style.display = 'block';
      elements.timelineList.style.display = 'none';
      elements.timelineStepCount.textContent = t('timeline.stepsCount', { current: 0, total: 9 });
      return;
    }

    // Explicit sort by execution sequence
    const sortedSteps = [...timelineSteps].sort((a, b) => {
      const orderA = a.stepOrder ?? a.step_number ?? (a.timestamp ? a.timestamp * 1000 : 0);
      const orderB = b.stepOrder ?? b.step_number ?? (b.timestamp ? b.timestamp * 1000 : 0);
      if (orderA !== orderB) return orderA - orderB;
      return (a.timestamp || 0) - (b.timestamp || 0);
    });

    state.lastTimelineSteps = sortedSteps;

    elements.timelineEmptyState.style.display = 'none';
    elements.timelineList.style.display = 'flex';
    elements.timelineList.innerHTML = '';
    elements.timelineStepCount.textContent = t('timeline.stepsCount', {
      current: sortedSteps.length,
      total: 9,
    });

    sortedSteps.forEach((step, idx) => {
      // 1-based normalized index for sequential display
      const normalizedStepNum = idx + 1;
      const statusKey = step.status || 'INFO';
      const statusClass = statusKey.toLowerCase().replace('_', '-');

      // Translate step name and status
      const translatedName = t(`steps.${step.name}`, {}, step.name);
      const translatedStatus = t(`status.${statusKey}`, {}, statusKey);
      const stepTooltip = t('timeline.stepTooltip', { num: normalizedStepNum });
      const viewPayloadText = t('timeline.viewPayload');
      const hidePayloadText = t('timeline.hidePayload');
      const toolLabelText = t('timeline.toolLabel');

      const item = document.createElement('div');
      item.className = `timeline-item ${statusClass}`;

      const stepId = `step-details-${idx}`;

      item.innerHTML = `
        <div class="step-num-badge" title="${stepTooltip}" aria-label="${stepTooltip}">
          ${normalizedStepNum}
        </div>
        <div class="step-content">
          <div class="step-header">
            <span class="step-name">${escapeHtml(translatedName)}</span>
            <span class="step-badge ${statusClass}">${escapeHtml(translatedStatus)}</span>
          </div>
          ${step.duration_ms ? `<div class="step-duration">${step.duration_ms} ms</div>` : ''}
          ${step.tool_name ? `<div class="step-tool-tag">${toolLabelText} <strong>${escapeHtml(step.tool_name)}</strong></div>` : ''}

          ${step.result || step.sanitized_parameters || step.error ? `
            <button type="button" class="step-details-toggle" data-target="${stepId}">
              <span>${icons.chevronDown}</span>
              <span class="toggle-label">${viewPayloadText}</span>
            </button>
            <div class="step-details-box" id="${stepId}">
              ${escapeHtml(JSON.stringify(step.result || step.sanitized_parameters || { error: step.error }, null, 2))}
            </div>
          ` : ''}
        </div>
      `;

      elements.timelineList.appendChild(item);
    });

    // Attach toggle listeners with localized labels
    elements.timelineList.querySelectorAll('.step-details-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-target');
        const box = document.getElementById(targetId);
        const labelSpan = btn.querySelector('.toggle-label');
        if (box) {
          box.classList.toggle('open');
          const isOpen = box.classList.contains('open');
          btn.querySelector('span:first-child').innerHTML = isOpen ? icons.chevronUp : icons.chevronDown;
          if (labelSpan) {
            labelSpan.textContent = isOpen ? t('timeline.hidePayload') : t('timeline.viewPayload');
          }
        }
      });
    });
  }


  return { renderTimeline };
}
