from typing import List, Dict
import aiohttp
import pandas

url = {'home': 'http://192.168.86.31',
       'external': 'http://73.168.19.100:5000'}


class EMonitorWebPage:
  def __init__(self, location):
    self.location_ = location

  async def get(self) -> List[Dict[str, str]]:
    async with aiohttp.ClientSession() as session:
      async with session.get(url[self.location_]) as response:
        html = await response.text()

        html_tables = pandas.read_html(html)
        data = html_tables[1]
        data_dict = data.to_dict('records')
        return data_dict

  async def get_meta(self) -> List[Dict[str, str]]:
    async with aiohttp.ClientSession() as session:
      async with session.get(f'{url[self.location_]}/channel.html') as response:
        html = await response.text()

        html_tables = pandas.read_html(html)
        data = html_tables[1]
        data_dict = data.to_dict('records')
        return data_dict
