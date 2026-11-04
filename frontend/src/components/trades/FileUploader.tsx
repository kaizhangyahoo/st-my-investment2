import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { UploadCloud, CheckCircle2, AlertCircle } from 'lucide-react';
import { portfolioApi } from '../../services/api';

interface FileUploaderProps {
  onUploadSuccess: () => void;
}

export const FileUploader: React.FC<FileUploaderProps> = ({ onUploadSuccess }) => {
  const [uploading, setUploading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    setUploading(true);
    setStatusMessage(null);
    try {
      const res = await portfolioApi.uploadFiles(acceptedFiles);
      const total = (res.trade_files?.length || 0) + (res.transaction_files?.length || 0);
      setStatusMessage({
        type: 'success',
        text: `Successfully uploaded ${total} file(s)`,
      });
      onUploadSuccess();
    } catch (err: any) {
      setStatusMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Failed to upload files',
      });
    } finally {
      setUploading(false);
    }
  }, [onUploadSuccess]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/csv': ['.csv'] },
  });

  return (
    <div className="w-full">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-950/20'
            : 'border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600 bg-white dark:bg-slate-900'
        }`}
      >
        <input {...getInputProps()} />
        <UploadCloud className="w-10 h-10 mx-auto text-slate-400 mb-2" />
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {isDragActive ? 'Drop your CSV files here' : 'Drag & drop Trade*.csv or Transaction*.csv here, or click to browse'}
        </p>
        <p className="text-xs text-slate-400 mt-1">Supports IG Broker Trade and Transaction export formats</p>
      </div>

      {uploading && <div className="mt-2 text-xs text-blue-500 font-medium">Processing files & calculating valuation...</div>}
      {statusMessage && (
        <div
          className={`mt-2 p-2.5 rounded-lg text-xs flex items-center ${
            statusMessage.type === 'success'
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400'
              : 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-400'
          }`}
        >
          {statusMessage.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 mr-1.5 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 mr-1.5 flex-shrink-0" />
          )}
          {statusMessage.text}
        </div>
      )}
    </div>
  );
};

