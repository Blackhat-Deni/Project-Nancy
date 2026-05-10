import subprocess
import json
import os
import pathlib
import time

class TradingViewControl:
    """
    A Python wrapper around the tradingview-mcp-jackson CLI tool ('tv').
    This class allows Nancy to programmatically switch symbols, fetch live quotes,
    check connection status, and take screenshots of the charts by calling the underlying CLI.
    """

    def __init__(self):
        # Determine the root of the project to construct absolute paths for saving files.
        # This file is in app/mcp/, so we go two levels up to reach project-nancy
        self.project_root = pathlib.Path(__file__).resolve().parents[2]
        self.tv_path = "/home/deni/.nvm/versions/node/v24.14.1/bin/tv"
        
    def _run_tv_command(self, command: list[str], timeout: int = 5) -> dict:
        """
        Helper method to run a 'tv' command via the subprocess module and parse the JSON output.
        
        Args:
            command: A list of string arguments for the command, e.g., ["tv", "status"]
            timeout: Maximum seconds to wait for the command to complete.
            
        Returns:
            A dictionary containing the parsed JSON data, or an error dictionary if it fails.
        """
        try:
            # Run the command. We capture stdout and stderr so we can parse them.
            # text=True ensures we get strings back instead of raw bytes.
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True # Raises a CalledProcessError if the command fails (exit code != 0)
            )
            
            # If successful, parse the standard output as JSON
            return json.loads(result.stdout)
            
        except subprocess.TimeoutExpired:
            # The command took longer than the specified timeout
            return {"error": "Timeout", "message": f"Command {' '.join(command)} took longer than {timeout} seconds."}
            
        except subprocess.CalledProcessError as e:
            # The command failed (non-zero exit code). Try to see if it returned JSON error details, otherwise use raw stderr
            try:
                error_data = json.loads(e.stdout)
                return {"error": "CommandFailed", "details": error_data}
            except json.JSONDecodeError:
                return {"error": "CommandFailed", "message": e.stderr.strip() or "Unknown error occurred"}
                
        except json.JSONDecodeError as e:
            # The command succeeded but the output was not valid JSON
            return {"error": "ParseError", "message": f"Failed to parse JSON output: {str(e)}", "raw_output": result.stdout}
            
        except Exception as e:
            # Catch any other unexpected errors
            return {"error": "UnexpectedError", "message": str(e)}

    def get_status(self) -> dict:
        """
        Checks the connection status to the TradingView client.
        Calls: `tv status`
        
        Returns:
            A dictionary with status information.
        """
        print("[INFO] Checking TradingView connection status...")
        return self._run_tv_command([self.tv_path, "status"])

    def get_quote(self, symbol: str) -> dict:
        """
        Fetches the current OHLCV (Open, High, Low, Close, Volume) data.
        Calls: `tv quote`
        
        Args:
            symbol: The ticker symbol to get a quote for.
            
        Returns:
            A dictionary containing the quote data.
        """
        print(f"[INFO] Fetching live quote for {symbol}...")
        
        # Depending on the CLI implementation, it might take the symbol as an argument
        # e.g., `tv quote GBPUSD`. If it only uses the active chart, this will safely pass it anyway.
        return self._run_tv_command([self.tv_path, "quote", symbol])

    def switch_symbol(self, symbol: str) -> dict:
        """
        Switches the active chart to the specified symbol.
        Calls: `tv symbol {symbol}`
        
        Args:
            symbol: The ticker symbol to switch to (e.g., 'GBPUSD', 'AAPL')
            
        Returns:
            A dictionary confirming success or failure.
        """
        print(f"[INFO] Switching TradingView chart to {symbol}...")
        return self._run_tv_command([self.tv_path, "symbol", symbol], timeout=15)

    def take_screenshot(self) -> dict:
        """
        Takes a screenshot of the current TradingView chart and saves it.
        Calls `tv screenshot` with a 10-second timeout.
        
        Returns:
            A dictionary containing the file path to the saved screenshot or an error.
        """
        print("[INFO] Taking a screenshot of the current chart (this may take up to 10 seconds)...")
        
        # Ensure the screenshots directory exists
        screenshots_dir = self.project_root / "data" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate a unique filename using a timestamp
        timestamp = int(time.time())
        filename = f"tv_screenshot_{timestamp}.png"
        filepath = str(screenshots_dir / filename)
        
        # Run the command with a longer 10-second timeout.
        # We pass the filepath so the CLI knows where to save the image.
        command = [self.tv_path, "screenshot", filepath]
        
        result = self._run_tv_command(command, timeout=10)
        
        # If successful, inject the filepath into the result so the caller knows where it is
        if "error" not in result:
            result["filepath"] = filepath
            
        return result

if __name__ == "__main__":
    # -------------------------------------------------------------------------
    # Test Block
    # This runs only if you execute this file directly: python app/mcp/tradingview_control.py
    # -------------------------------------------------------------------------
    
    print("="*50)
    print("TradingView Control - Quick Test")
    print("="*50)
    
    # Initialize our controller
    tv = TradingViewControl()
    
    # 1. Test get_status()
    print("\n--- Testing get_status() ---")
    status = tv.get_status()
    print(json.dumps(status, indent=2))
    
    # 2. Test switch_symbol("GBPUSD")
    print("\n--- Testing switch_symbol('GBPUSD') ---")
    switch_res = tv.switch_symbol("GBPUSD")
    print(json.dumps(switch_res, indent=2))
    
    # 3. Test get_quote()
    # Fetch quote for the symbol we just switched to
    print("\n--- Testing get_quote('GBPUSD') ---")
    quote = tv.get_quote("GBPUSD")
    print(json.dumps(quote, indent=2))
    
    print("\nTest complete.")
