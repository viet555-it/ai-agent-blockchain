"use client";

import React, { useState } from "react";
import { TransactionAction } from "@/services/api";
import { useWallet } from "@/context/WalletContext";
import { ArrowUpRight, CheckCircle, AlertTriangle, Loader2, Sparkles, ExternalLink, ShieldCheck, ShieldAlert, FileCode2 } from "lucide-react";

interface TransactionCardProps {
  transaction: TransactionAction;
}

export const TransactionCard: React.FC<TransactionCardProps> = ({ transaction }) => {
  const { sendPreparedTransaction, isConnected, connectWallet } = useWallet();
  const [status, setStatus] = useState<"idle" | "signing" | "success" | "error">("idle");
  const [txHash, setTxHash] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  const handleExecute = async () => {
    if (!isConnected) {
      await connectWallet();
      return;
    }

    try {
      setStatus("signing");
      setErrorMessage(null);

      const hash = await sendPreparedTransaction({
        to: transaction.to,
        value: transaction.value || "0",
        data: transaction.data || "0x",
        gasLimit: transaction.gas_limit,
      });

      setTxHash(hash);
      setStatus("success");
    } catch (err: any) {
      console.error("Execution failed:", err);
      setStatus("error");
      setErrorMessage(err.message || "Giao dịch bị từ chối hoặc gặp lỗi.");
    }
  };

  const getExplorerUrl = (hash: string) => {
    if (transaction.chain_id === 11155111) {
      return `https://sepolia.etherscan.io/tx/${hash}`;
    }
    return `https://etherscan.io/tx/${hash}`;
  };

  const isGuardrailPassed = transaction.guardrail?.is_safe !== false;

  return (
    <div className="mt-3 p-4 rounded-xl bg-card border border-indigo-500/30 bg-gradient-to-b from-indigo-950/20 to-card shadow-lg shadow-indigo-950/30">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/80 pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <span className="text-xs font-semibold text-white uppercase tracking-wider">
              {transaction.type === "transfer_native"
                ? "Giao dịch gửi ETH"
                : transaction.type === "transfer_token"
                ? "Giao dịch chuyển Token"
                : transaction.type === "mint_nft"
                ? "Giao dịch Mint NFT"
                : "Hành động Smart Contract"}
            </span>
            <p className="text-[11px] text-gray-400">{transaction.description}</p>
          </div>
        </div>
        <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
          Chain ID: {transaction.chain_id}
        </span>
      </div>

      {/* Guardrail Policy Badge */}
      {transaction.guardrail && (
        <div className="mt-2.5 p-2 rounded-lg bg-background/80 border border-border flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-1.5">
            {isGuardrailPassed ? (
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <ShieldAlert className="h-3.5 w-3.5 text-red-400" />
            )}
            <span className={isGuardrailPassed ? "text-emerald-400 font-medium" : "text-red-400 font-medium"}>
              Guardrail Policy: {transaction.guardrail.status}
            </span>
          </div>
          <span className="text-[10px] text-gray-400 font-mono">
            {transaction.guardrail.human_approval_required ? "Human Approval Enforced" : "Auto"}
          </span>
        </div>
      )}

      {/* Transaction Details */}
      <div className="py-3 space-y-2 text-xs font-mono">
        <div className="flex justify-between items-center text-gray-400">
          <span>Tới địa chỉ:</span>
          <span className="text-gray-200 truncate max-w-[220px]" title={transaction.to}>
            {transaction.to}
          </span>
        </div>
        {transaction.value_eth && transaction.value_eth !== "0" && (
          <div className="flex justify-between items-center text-gray-400">
            <span>Số lượng ETH:</span>
            <span className="text-indigo-300 font-bold">{transaction.value_eth} ETH</span>
          </div>
        )}
        {transaction.params?.token_symbol && (
          <div className="flex justify-between items-center text-gray-400">
            <span>Token:</span>
            <span className="text-emerald-400 font-bold">
              {transaction.params.amount} {transaction.params.token_symbol}
            </span>
          </div>
        )}
        <div className="flex justify-between items-center text-gray-400">
          <span>Gas Limit (Simulated):</span>
          <span className="text-gray-300">{transaction.gas_limit || "21,000"}</span>
        </div>
      </div>

      {/* Raw Payload toggle */}
      <div className="border-t border-border/60 pt-2">
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="text-[10px] text-gray-400 hover:text-indigo-300 flex items-center gap-1 transition-colors"
        >
          <FileCode2 className="h-3 w-3" />
          <span>{showDetails ? "Ẩn Call Data" : "Xem Call Data & Calldata Hex"}</span>
        </button>
        {showDetails && (
          <div className="mt-2 p-2 rounded bg-background border border-border text-[10px] font-mono text-gray-400 break-all">
            {transaction.data}
          </div>
        )}
      </div>

      {/* Success View */}
      {status === "success" && txHash && (
        <div className="mt-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-emerald-400 shrink-0" />
            <span className="font-sans">Giao dịch đã được phát lên mạng!</span>
          </div>
          <a
            href={getExplorerUrl(txHash)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300 underline font-mono text-[11px]"
          >
            <span>{txHash.slice(0, 8)}...</span>
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      )}

      {/* Error View */}
      {status === "error" && errorMessage && (
        <div className="mt-3 p-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
          <span className="font-sans">{errorMessage}</span>
        </div>
      )}

      {/* Action Buttons */}
      {status !== "success" && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={handleExecute}
            disabled={status === "signing" || !isGuardrailPassed}
            className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 active:scale-[0.99] disabled:opacity-50 text-white text-xs font-semibold shadow-md shadow-indigo-600/30 transition-all"
          >
            {status === "signing" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Đang chờ ký trên Ví (Human-in-the-loop)...</span>
              </>
            ) : (
              <>
                <ArrowUpRight className="h-3.5 w-3.5" />
                <span>Xác nhận & Ký trên Ví</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
};
