from flask import Flask,render_template,Response
from EMonitorDB import EMonitorDBReader
from datetime import datetime

db=EMonitorDBReader()

db.load_latest()

app=Flask(__name__)

@app.route('/')
def current():
  current_power=db.load_latest()
  rows=[]
  max_time=None
  for circuit in current_power:
    row_vals={}
    row_vals['id']=circuit.get('id',0)
    row_vals['name']=circuit.get('name','NA')
    row_vals['power']=circuit.get('power',0)
    if max_time is None or circuit['time']>max_time:
      max_time=circuit['time']
    rows.append(row_vals)
  return render_template('/current.html',data=rows,time=str(max_time))

if __name__ == '__main__':
    app.run(host='0.0.0.0')