/**
 * Deploy Datachain to Polygon Amoy (CP-D.P4).
 *
 * From contracts/ (never commit AMOY_PRIVATE_KEY):
 *
 *   npx hardhat run scripts/deploy.ts --network polygonAmoy
 *
 * Requires AMOY_RPC_URL and AMOY_PRIVATE_KEY (see .env.example).
 * The deployer becomes the contract owner (only writer).
 */

import hre from "hardhat";

const AMOY_CHAIN_ID = 80002;
const POLYGONSCAN_AMOY = "https://amoy.polygonscan.com/address";

async function main(): Promise<void> {
  const connection = await hre.network.connect();
  const networkName = connection.networkName;
  if (networkName !== "polygonAmoy") {
    throw new Error(
      `Refusing to deploy on "${networkName}". Use --network polygonAmoy.`,
    );
  }

  const { viem } = connection;
  const [wallet] = await viem.getWalletClients();
  if (wallet === undefined) {
    throw new Error("No wallet on polygonAmoy; set AMOY_PRIVATE_KEY.");
  }
  const chainId = await wallet.getChainId();
  if (chainId !== AMOY_CHAIN_ID) {
    throw new Error(
      `Expected Polygon Amoy chain id ${AMOY_CHAIN_ID}, got ${chainId}.`,
    );
  }

  const datachain = await viem.deployContract("Datachain");
  const address = datachain.address;
  console.log("Datachain deployed on Polygon Amoy");
  console.log(`address=${address}`);
  console.log(`explorer=${POLYGONSCAN_AMOY}/${address}`);
  console.log(
    "Copy the address into backend .env as DATACHAIN_CONTRACT_ADDRESS when wiring Web3.py (later slice).",
  );
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
