"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { BrowserProvider, JsonRpcSigner, formatEther } from "ethers";

interface WalletContextType {
  address: string | null;
  chainId: number | null;
  chainName: string;
  balance: string;
  isConnected: boolean;
  isConnecting: boolean;
  error: string | null;
  connectWallet: () => Promise<void>;
  disconnectWallet: () => void;
  sendPreparedTransaction: (tx: { to: string; value: string; data: string; gasLimit?: string }) => Promise<string>;
  switchNetwork: (targetChainId: number) => Promise<void>;
}

const WalletContext = createContext<WalletContextType | undefined>(undefined);

const CHAIN_NAMES: Record<number, string> = {
  1: "Ethereum Mainnet",
  11155111: "Sepolia Testnet",
  137: "Polygon",
  80001: "Mumbai",
  31337: "Hardhat / Localhost",
};

export const WalletProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [address, setAddress] = useState<string | null>(null);
  const [chainId, setChainId] = useState<number | null>(11155111);
  const [balance, setBalance] = useState<string>("0.0");
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const getEthereumObject = () => {
    if (typeof window !== "undefined" && (window as any).ethereum) {
      return (window as any).ethereum;
    }
    return null;
  };

  const updateWalletState = async (provider: BrowserProvider, currentAddress: string) => {
    try {
      const network = await provider.getNetwork();
      setChainId(Number(network.chainId));

      const balWei = await provider.getBalance(currentAddress);
      const balEth = formatEther(balWei);
      setBalance(parseFloat(balEth).toFixed(4));
    } catch (e: any) {
      console.error("Error updating wallet state:", e);
    }
  };

  const connectWallet = async () => {
    setError(null);
    setIsConnecting(true);
    const ethereum = getEthereumObject();

    if (!ethereum) {
      // If MetaMask is not installed, provide a mock/test wallet address for smooth local testing
      const mockAddress = "0x71C9491133502447972423423719011234567890";
      setAddress(mockAddress);
      setChainId(11155111);
      setBalance("1.2540");
      setIsConnecting(false);
      return;
    }

    try {
      const provider = new BrowserProvider(ethereum);
      const accounts = await provider.send("eth_requestAccounts", []);
      if (accounts && accounts.length > 0) {
        setAddress(accounts[0]);
        await updateWalletState(provider, accounts[0]);
      }
    } catch (err: any) {
      setError(err.message || "Failed to connect wallet");
    } finally {
      setIsConnecting(false);
    }
  };

  const disconnectWallet = () => {
    setAddress(null);
    setBalance("0.0");
  };

  const switchNetwork = async (targetChainId: number) => {
    const ethereum = getEthereumObject();
    if (!ethereum) {
      setChainId(targetChainId);
      return;
    }
    try {
      const hexChainId = "0x" + targetChainId.toString(16);
      await ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: hexChainId }],
      });
      setChainId(targetChainId);
    } catch (e: any) {
      console.error("Switch network error:", e);
    }
  };

  const sendPreparedTransaction = async (tx: { to: string; value: string; data: string; gasLimit?: string }): Promise<string> => {
    const ethereum = getEthereumObject();
    if (!ethereum) {
      // Mock simulation mode when wallet not connected
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const mockTxHash = "0x" + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
      return mockTxHash;
    }

    const provider = new BrowserProvider(ethereum);
    const signer = await provider.getSigner();

    const txResponse = await signer.sendTransaction({
      to: tx.to,
      value: tx.value ? BigInt(tx.value) : BigInt(0),
      data: tx.data || "0x",
      gasLimit: tx.gasLimit ? BigInt(tx.gasLimit) : undefined,
    });

    // Refresh balance after sending
    if (address) {
      setTimeout(() => updateWalletState(provider, address), 4000);
    }

    return txResponse.hash;
  };

  useEffect(() => {
    const ethereum = getEthereumObject();
    if (ethereum) {
      const handleAccountsChanged = (accounts: string[]) => {
        if (accounts.length > 0) {
          setAddress(accounts[0]);
          const provider = new BrowserProvider(ethereum);
          updateWalletState(provider, accounts[0]);
        } else {
          disconnectWallet();
        }
      };

      const handleChainChanged = () => {
        window.location.reload();
      };

      ethereum.on("accountsChanged", handleAccountsChanged);
      ethereum.on("chainChanged", handleChainChanged);

      return () => {
        if (ethereum.removeListener) {
          ethereum.removeListener("accountsChanged", handleAccountsChanged);
          ethereum.removeListener("chainChanged", handleChainChanged);
        }
      };
    }
  }, [address]);

  const chainName = chainId ? CHAIN_NAMES[chainId] || `Chain ${chainId}` : "Sepolia Testnet";

  return (
    <WalletContext.Provider
      value={{
        address,
        chainId,
        chainName,
        balance,
        isConnected: !!address,
        isConnecting,
        error,
        connectWallet,
        disconnectWallet,
        sendPreparedTransaction,
        switchNetwork,
      }}
    >
      {children}
    </WalletContext.Provider>
  );
};

export const useWallet = () => {
  const context = useContext(WalletContext);
  if (!context) {
    throw new Error("useWallet must be used within a WalletProvider");
  }
  return context;
};

