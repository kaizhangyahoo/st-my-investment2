import React from 'react';

interface CardProps {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({ title, subtitle, children, className = '', action }) => {
  return (
    <div className={`bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm p-5 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-4">
          <div>
            {title && <h3 className="font-semibold text-slate-800 dark:text-slate-100 text-lg">{title}</h3>}
            {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
};

