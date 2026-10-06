import re
from typing import Any, Dict, List, Optional

RAG_KNOWLEDGE_BASE = [
    {
        "id": "doc_erc20_standard",
        "title": "ERC-20 Token Standard Specification",
        "category": "Smart Contract ABI",
        "content": """Chuẩn ERC-20 bao gồm các hàm:
- transfer(address to, uint256 value) -> bool: Chuyển token từ caller đến ví người nhận. Cần chú ý nhân số lượng với 10^decimals.
- balanceOf(address owner) -> uint256: Tra cứu số dư token của ví.
- approve(address spender, uint256 value) -> bool: Cấp quyền cho contract tiêu dùng token.
- decimals() -> uint8: Số chữ số thập phân (thông thường 18 hoặc 6 đối với USDC).
Địa chỉ testnet phổ biến: Sepolia USDC (0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238), LINK (0x779877A7B0D9E8603169DdbD7836e478b4624789)."""
    },
    {
        "id": "doc_erc721_nft",
        "title": "ERC-721 NFT Minting Specification",
        "category": "Smart Contract ABI",
        "content": """Chuẩn ERC-721 đại diện cho Non-Fungible Token (NFT):
- mintNFT(address recipient, string memory uri) -> uint256: Mint 1 NFT mới với IPFS metadata URI gửi về địa chỉ ví người nhận.
- ownerOf(uint256 tokenId) -> address: Xác định chủ sở hữu của tokenId.
- balanceOf(address owner) -> uint256: Số lượng NFT ví đang sở hữu."""
    },
    {
        "id": "doc_guardrail_policy",
        "title": "Guardrail & Safety Policies",
        "category": "Security & Policy",
        "content": """Quy định an toàn giao dịch (Guardrail Policy):
- Hạn mức tối đa cho mỗi giao dịch Native (ETH) tự động: 0.1 ETH.
- Hạn mức tối đa cho mỗi giao dịch Token (USDC/LINK): 500 Token.
- Bắt buộc kiểm tra địa chỉ định dạng EIP-55 Checksum trước khi tạo transaction.
- Chặn tuyệt đối các giao dịch gửi đến địa chỉ 0x0000... hoặc ví Blacklist.
- Yêu cầu người dùng trực tiếp xác nhận chữ ký trên ví Web3 (Human-in-the-loop), Agent không tự ký riêng tư."""
    },
    {
        "id": "doc_gas_simulation",
        "title": "Gas Estimation & Transaction Simulation",
        "category": "Blockchain Execution",
        "content": """Quy trình gửi giao dịch an toàn:
1. Dry-run / Simulate: Ước tính Gas Limit trước khi gửi (Native Transfer: 21000 Gas, ERC20: ~65000 Gas, NFT Mint: ~150000 Gas).
2. Kiểm tra số dư ví người gửi để đảm bảo đủ trả lượng chuyển + phí Gas.
3. Trả về tx hash và liên kết theo dõi trên Etherscan Explorer."""
    }
]

class RAGService:
    def __init__(self):
        self.documents = RAG_KNOWLEDGE_BASE

    def retrieve(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """
        Retrieves top-k relevant knowledge chunks based on query terms.
        """
        query_terms = set(re.findall(r"\w+", query.lower()))
        scored_docs = []
        
        for doc in self.documents:
            text_corpus = (doc["title"] + " " + doc["content"] + " " + doc["category"]).lower()
            score = 0
            for term in query_terms:
                if term in text_corpus:
                    score += 1
            if score > 0:
                scored_docs.append((score, doc))
                
        # Sort descending by score
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        
        if not scored_docs:
            return self.documents[:top_k]
            
        return [doc for score, doc in scored_docs[:top_k]]

    def get_all_documents(self) -> List[Dict[str, Any]]:
        return self.documents

rag_service = RAGService()

