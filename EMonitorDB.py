from typing import List, Dict
import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class MetaData(Base):
  __tablename__ = 'meta_data'
  id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
  name = sqlalchemy.Column(sqlalchemy.String(length=20))
  input = sqlalchemy.Column(sqlalchemy.Boolean)
  rating = sqlalchemy.Column(sqlalchemy.Integer)
  voltage = sqlalchemy.Column(sqlalchemy.Integer)
  paired = sqlalchemy.Column(sqlalchemy.Integer)
  def __repr__(self):
    return f'<meta_data(id={self.id},' \
           f' name={self.name},' \
           f' input={self.input},' \
           f' rating={self.rating}' \
           f' voltage={self.voltage}' \
           f' paired={self.paired}' \
           f'>'

class RawData(Base):
  __tablename__ = 'raw_data'
  time = sqlalchemy.Column(sqlalchemy.DateTime, primary_key=True)
  id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
  power = sqlalchemy.Column(sqlalchemy.Integer)

  def __repr__(self):
    return f'<raw_data(time={self.time}, id={self.id}, channel={self.channel}, power={self.power}>'


class EMonitorDB:
  def __init__(self):
    self.host_ = "localhost"
    self.engine_ = sqlalchemy.create_engine(
      'mysql+mysqlconnector://writer:writer@localhost:3306/emonitor',
      echo=True)
    Base.metadata.create_all(self.engine_)

    Session = sqlalchemy.orm.sessionmaker()
    Session.configure(bind=self.engine_)
    self.session_ = Session()

  def store(self, values: List[Dict[str, str]]):
    now=datetime.now ()
    for row in values:
      id = row.get('#', None)
      power = row.get('Power (w)', 'NA')

      db_row = RawData(time=now, id=id, power=power)
      self.session_.add (db_row)
    self.session_.commit ()

  def store_meta(self, values: List[Dict[str,str]]):
    for row in values:
      id = int (row.get('#', None))
      name = row.get('Name', 'NA')
      input = {0: False, 1: True}.get (row.get('Input', 0))
      rating = int(row.get('CT Rating',0))
      voltage = int(row.get('Voltage',0))
      paired = int(row.get('Paired',0))

      db_row = MetaData(id=id, name=name, input=input, rating=rating, voltage=voltage, paired=paired )
      self.session_.merge (db_row)
    self.session_.commit ()