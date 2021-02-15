from typing import List, Dict
import sqlalchemy
from sqlalchemy import func
from sqlalchemy import and_
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import logging

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
    return f'<raw_data(time={self.time}, id={self.id}, power={self.power}>'


class EMonitorDB:
  def __init__(self):
    self.logger_ = logging.getLogger('main')
    self.host_ = "localhost"
    self.engine_ = sqlalchemy.create_engine(
      'mysql+mysqlconnector://writer:writer@localhost:3306/emonitor',
      echo=False)
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
    self.logger_.debug (f'Written {len(values)} rows to emonitor.raw_data')

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
    self.logger_.info(f'Updated emonitor.meta_data')

class EMonitorDBReader:
  def __init__(self):
    self.logger_ = logging.getLogger('main')
    self.host_ = "localhost"
    self.engine_ = sqlalchemy.create_engine(
      'mysql+mysqlconnector://writer:writer@localhost:3306/emonitor',
      echo=True)
    Base.metadata.create_all(self.engine_)

    Session = sqlalchemy.orm.sessionmaker()
    Session.configure(bind=self.engine_)
    self.session_ = Session()
    self.meta_data_={}
    self._load_meta()

  def _load_meta(self):
    for row in self.session_.query(MetaData).all():
      self.meta_data_ [row.id]={'id': row.id,
                                'input': row.input,
                                'name': row.name,
                                'paired': row.paired,
                                'rating': row.rating,
                                'voltage': row.voltage,
                                }

  def load_latest(self):
    max_query=self.session_.query(RawData.id,func.max(RawData.time).label('max_timestamp')).group_by (RawData.id).subquery()
    query2=self.session_.query(RawData).join(max_query, and_(RawData.id == max_query.c.id, RawData.time == max_query.c.max_timestamp))
    #query3=self.session_.query(query2.c.id, query2.c.power,MetaData).filter(query2.c.id == MetaData.id)

    ret_val=[]
    for row in query2.all ():
      id=row.id
      power=row.power
      time=row.time
      ret_dict=self.meta_data_.get (id,{})
      ret_dict ['power']=power
      ret_dict ['time']=time
      ret_val.append(ret_dict)
    return ret_val

