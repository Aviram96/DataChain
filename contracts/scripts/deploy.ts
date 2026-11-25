/**
 * Deploy Datachain. The deployer becomes the contract owner (only writer).
 *
 * Polygon Amoy (CP-D.P4), from contracts/ (never commit AMOY_PRIVATE_KEY):
 *
 *   npx hardhat run scripts/deploy.ts --network polygonAmoy
 *
 * Requires AMOY_RPC_URL and AMOY_PRIVATE_KEY (see .env.example).
 *
 * Local Hardhat 3 node (chain id 31337), after `npx hardhat node`:
 *
 *   npx hardhat run scripts/deploy.ts --network localhost
 *
 * The built-in localhost network is http://127.0.0.1:8545. It uses the node's
 * unlocked accounts, so no private key is passed on the command line.
 */

import hre from "hardhat";

const AMOY_CHAIN_ID = 80002;
const LOCAL_CHAIN_ID = 31337;
const POLYGONSCAN_AMOY = "https://amoy.polygonscan.com/address";

function deployerAddress(account: { address: string } | string): string {
  return typeof account === "string" ? account : account.address;
}

async function main(): Promise<void> {
  const connection = await hre.network.connect();
  const networkName = connection.networkName;
  if (networkName !== "polygonAmoy" && networkName !== "localhost") {
    throw new Error(
      `Refusing to deploy on "${networkName}". Use --network polygonAmoy or --network localhost.`,
    );
  }

  const { viem } = connection;
  const [wallet] = await viem.getWalletClients();
  if (wallet === undefined) {
    throw new Error(
      networkName === "polygonAmoy"
        ? "No wallet on polygonAmoy; set AMOY_PRIVATE_KEY."
        : "No wallet on localhost. Start `npx hardhat node` first.",
    );
  }
  const chainId = await wallet.getChainId();
  const expectedChainId =
    networkName === "polygonAmoy" ? AMOY_CHAIN_ID : LOCAL_CHAIN_ID;
  if (chainId !== expectedChainId) {
    const label =
      networkName === "polygonAmoy" ? "Polygon Amoy" : "local Hardhat";
    throw new Error(
      `Expected ${label} chain id ${expectedChainId}, got ${chainId}.`,
    );
  }

  const datachain = await viem.deployContract("Datachain");
  const address = datachain.address;
  const owner = await datachain.read.owner();
  const deployer = deployerAddress(wallet.account);
  if (owner.toLowerCase() !== deployer.toLowerCase()) {
    throw new Error(
      `Deployer ${deployer} is not the contract owner ${owner}.`,
    );
  }

  if (networkName === "polygonAmoy") {
    console.log("Datachain deployed on Polygon Amoy");
    console.log(`address=${address}`);
    console.log(`explorer=${POLYGONSCAN_AMOY}/${address}`);
    console.log(
      "Copy the address into backend .env as DATACHAIN_CONTRACT_ADDRESS when wiring Web3.py (later slice).",
    );
    return;
  }

  console.log("Datachain deployed on local Hardhat");
  console.log(`address=${address}`);
  console.log(`chainId=${chainId}`);
  console.log(`deployer=${deployer}`);
  console.log(`owner=${owner}`);
  console.log("rpc=http://127.0.0.1:8545");
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
