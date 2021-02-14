from typing import List, Dict
import aiohttp
import pandas


class EMonitorWebPage:
  def __init__(self):
    print("Init")

  async def get(self)->List[Dict[str,str]]:
    async with aiohttp.ClientSession() as session:
      async with session.get('http://192.168.86.31') as response:
        html = await response.text()

        html_tables = pandas.read_html (html)
        data = html_tables[1]
        data_dict = data.to_dict ('records')
        return data_dict





