import React from 'react';
import { Modal } from '../common/Modal';
import { UnresolvedSymbol } from '../../types';

interface UnresolvedSymbolsModalProps {
  open: boolean;
  symbols: UnresolvedSymbol[];
  onDismiss: () => void;
}

const PREVIEW_LIMIT = 5;

// A short notice only: review, editing and saving happen in the Reference Data tab, which
// the dashboard has already switched to and where SEC suggestions are already loading.
export const UnresolvedSymbolsModal: React.FC<UnresolvedSymbolsModalProps> = ({
  open,
  symbols,
  onDismiss,
}) => {
  const affectedRows = symbols.reduce((acc, s) => acc + s.row_count, 0);
  const hidden = symbols.length - PREVIEW_LIMIT;

  return (
    <Modal
      open={open}
      title="Unmapped Symbols Detected"
      subtitle={`${symbols.length} instrument name${symbols.length === 1 ? '' : 's'} across ${affectedRows} trade row${affectedRows === 1 ? '' : 's'} cannot be resolved to a ticker.`}
      onDismiss={onDismiss}
      footer={
        <button
          type="button"
          onClick={onDismiss}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors"
        >
          <span className="material-symbols-outlined text-[15px]">tune</span>
          <span>REVIEW IN REFERENCE DATA</span>
        </button>
      }
    >
      <ul className="space-y-1 mb-space-sm">
        {symbols.slice(0, PREVIEW_LIMIT).map(({ market_name, row_count }) => (
          <li
            key={market_name}
            className="flex justify-between font-data-mono-sm text-xs text-on-surface"
          >
            <span className="truncate">{market_name}</span>
            <span className="text-outline shrink-0 ml-2">
              {row_count} row{row_count === 1 ? '' : 's'}
            </span>
          </li>
        ))}
        {hidden > 0 && (
          <li className="font-data-mono-sm text-[11px] text-outline">+ {hidden} more</li>
        )}
      </ul>

      <p className="font-body-sm text-[11px] text-on-surface-variant">
        SEC suggestions are being loaded in the Reference Data tab for you to review and save.
        Names you leave unsaved are excluded from positions and P&amp;L, and you will be prompted
        again on the next upload.
      </p>
    </Modal>
  );
};
