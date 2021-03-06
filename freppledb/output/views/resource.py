#
# Copyright (C) 2007-2013 by frePPLe bvba
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from django.db import connections
from django.db.models.expressions import RawSQL
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import string_concat

from freppledb.boot import getAttributeFields
from freppledb.input.models import Resource, Location, OperationPlanResource, Operation
from freppledb.input.views import OperationPlanMixin
from freppledb.common.models import Parameter
from freppledb.common.report import GridReport, GridPivot, GridFieldCurrency
from freppledb.common.report import GridFieldLastModified, GridFieldDuration
from freppledb.common.report import GridFieldDateTime, GridFieldInteger
from freppledb.common.report import GridFieldNumber, GridFieldText, GridFieldBool


class OverviewReport(GridPivot):
  '''
  A report showing the loading of each resource.
  '''
  template = 'output/resource.html'
  title = _('Resource report')
  basequeryset = Resource.objects.all()
  model = Resource
  permissions = (("view_resource_report", "Can view resource report"),)
  editable = False
  help_url = 'user-guide/user-interface/plan-analysis/resource-report.html'

  rows = (
    GridFieldText('resource', title=_('resource'), key=True, editable=False, field_name='name', formatter='detail', extra='"role":"input/resource"'),
    GridFieldText('description', title=_('description'), editable=False, field_name='description', initially_hidden=True),
    GridFieldText('category', title=_('category'), editable=False, field_name='category', initially_hidden=True),
    GridFieldText('subcategory', title=_('subcategory'), editable=False, field_name='subcategory', initially_hidden=True),
    GridFieldText('type', title=_('type'), editable=False, field_name='type', initially_hidden=True),
    GridFieldNumber('maximum', title=_('maximum'), editable=False, field_name='maximum', initially_hidden=True),
    GridFieldText('maximum_calendar', title=_('maximum calendar'), editable=False, field_name='maximum_calendar__name', formatter='detail', extra='"role":"input/calendar"', initially_hidden=True),
    GridFieldCurrency('cost', title=_('cost'), editable=False, field_name='cost', initially_hidden=True),
    GridFieldDuration('maxearly', title=_('maxearly'), editable=False, field_name='maxearly', initially_hidden=True),
    GridFieldText('setupmatrix', title=_('setupmatrix'), editable=False, field_name='setupmatrix__name', formatter='detail', extra='"role":"input/setupmatrix"', initially_hidden=True),
    GridFieldText('setup', title=_('setup'), editable=False, field_name='setup', initially_hidden=True),
    GridFieldText('location__name', title=_('location'), editable=False, field_name='location__name', formatter='detail', extra='"role":"input/location"'),
    GridFieldText('location__description', title=string_concat(_('location'), ' - ', _('description')), editable=False, initially_hidden=True),
    GridFieldText('location__category', title=string_concat(_('location'), ' - ', _('category')), editable=False, initially_hidden=True),
    GridFieldText('location__subcategory', title=string_concat(_('location'), ' - ', _('subcategory')), editable=False, initially_hidden=True),
    GridFieldText('location__available', title=string_concat(_('location'), ' - ', _('available')), editable=False, field_name='location__available__name', formatter='detail', extra='"role":"input/calendar"', initially_hidden=True),
    GridFieldText('avgutil', title=_('utilization %'), formatter='percentage', editable=False, width=100, align='center'),
    GridFieldText('available_calendar', title=_('available calendar'), editable=False, field_name='available__name', formatter='detail', extra='"role":"input/calendar"', initially_hidden=True),
    GridFieldText('owner', title=_('owner'), editable=False, field_name='owner__name', formatter='detail', extra='"role":"input/resource"', initially_hidden=True),
    )
  crosses = (
    ('available', {
       'title': _('available')
       }),
    ('unavailable', {'title': _('unavailable')}),
    ('setup', {'title': _('setup')}),
    ('load', {'title': _('load')}),
    ('utilization', {'title': _('utilization %')}),
    )

  @classmethod
  def initialize(reportclass, request):
    if reportclass._attributes_added != 2:
      reportclass._attributes_added = 2
      reportclass.attr_sql = ''
      # Adding custom resource attributes
      for f in getAttributeFields(Resource, initially_hidden=True):
        f.editable = False
        reportclass.rows += (f,)
        reportclass.attr_sql += 'res.%s, ' % f.name.split('__')[-1]
      # Adding custom location attributes
      for f in getAttributeFields(Location, related_name_prefix="location", initially_hidden=True):
        f.editable = False
        reportclass.rows += (f,)
        reportclass.attr_sql += 'location.%s, ' % f.name.split('__')[-1]

  @classmethod
  def extra_context(reportclass, request, *args, **kwargs):
    if args and args[0]:
      request.session['lasttab'] = 'plan'
      return {
        'units': reportclass.getUnits(request),
        'title': force_text(Resource._meta.verbose_name) + " " + args[0],
        'post_title': _('plan'),
        }
    else:
      return {'units': reportclass.getUnits(request)}

  @classmethod
  def basequeryset(reportclass, request, *args, **kwargs):
    return Resource.objects.all().annotate(
      avgutil=RawSQL('''
          select ( coalesce(sum(out_resourceplan.load),0) + coalesce(sum(out_resourceplan.setup),0) )
             * 100.0 / coalesce(greatest(sum(out_resourceplan.available), 0.0001),1) as avg_util
          from out_resourceplan
          where out_resourceplan.startdate >= %s
          and out_resourceplan.startdate < %s
          and out_resourceplan.resource = resource.name
          ''', (request.report_startdate, request.report_enddate)
         )
      )

  @classmethod
  def getUnits(reportclass, request):
    try:
      units = Parameter.objects.using(request.database).get(name="loading_time_units")
      if units.value == 'hours':
        return (1.0, _('hours'))
      elif units.value == 'weeks':
        return (1.0 / 168.0, _('weeks'))
      else:
        return (1.0 / 24.0, _('days'))
    except Exception:
      return (1.0 / 24.0, _('days'))

  @classmethod
  def query(reportclass, request, basequery, sortsql='1 asc'):
    basesql, baseparams = basequery.query.get_compiler(basequery.db).as_sql(with_col_aliases=False)

    # Get the time units
    units = OverviewReport.getUnits(request)

    # Assure the item hierarchy is up to date
    Resource.rebuildHierarchy(database=basequery.db)

    # Execute the query
    query = '''
      select res.name, res.description, res.category, res.subcategory,
        res.type, res.maximum, res.maximum_calendar_id, res.cost, res.maxearly,
        res.setupmatrix_id, res.setup, location.name, location.description,
        location.category, location.subcategory, location.available_id,
        res.avgutil, res.available_id available_calendar, res.owner_id,
        %s
        d.bucket as col1, d.startdate as col2,
        coalesce(sum(out_resourceplan.available),0) * (case when res.type = 'buckets' then 1 else %f end) as available,
        coalesce(sum(out_resourceplan.unavailable),0) * (case when res.type = 'buckets' then 1 else %f end) as unavailable,
        coalesce(sum(out_resourceplan.load),0) * (case when res.type = 'buckets' then 1 else %f end) as loading,
        coalesce(sum(out_resourceplan.setup),0) * (case when res.type = 'buckets' then 1 else %f end) as setup
      from (%s) res
      left outer join location
        on res.location_id = location.name
      -- Multiply with buckets
      cross join (
                   select name as bucket, startdate, enddate
                   from common_bucketdetail
                   where bucket_id = '%s' and enddate > '%s' and startdate < '%s'
                   ) d
      -- Utilization info
      left join out_resourceplan
      on res.name = out_resourceplan.resource
      and d.startdate <= out_resourceplan.startdate
      and d.enddate > out_resourceplan.startdate
      and out_resourceplan.startdate >= '%s'
      and out_resourceplan.startdate < '%s'
      -- Grouping and sorting
      group by res.name, res.description, res.category, res.subcategory,
        res.type, res.maximum, res.maximum_calendar_id, res.available_id, res.cost, res.maxearly,
        res.setupmatrix_id, res.setup, location.name, location.description,
        location.category, location.subcategory, location.available_id, res.avgutil, res.owner_id,
        %s d.bucket, d.startdate
      order by %s, d.startdate
      ''' % (
        reportclass.attr_sql, units[0], units[0], units[0], units[0],
        basesql, request.report_bucket, request.report_startdate,
        request.report_enddate,
        request.report_startdate, request.report_enddate,
        reportclass.attr_sql, sortsql
      )

    # Build the python result
    with connections[request.database].chunked_cursor() as cursor_chunked:
      cursor_chunked.execute(query, baseparams)
      for row in cursor_chunked:
        numfields = len(row)
        if row[numfields-4] != 0:
          util = row[numfields-2] * 100 / row[numfields-4]
        else:
          util = 0
        result = {
          'resource': row[0], 'description': row[1], 'category': row[2],
          'subcategory': row[3], 'type': row[4], 'maximum': row[5],
          'maximum_calendar': row[6], 'cost': row[7], 'maxearly': row[8],
          'setupmatrix': row[9], 'setup': row[10],
          'location__name': row[11], 'location__description': row[12],
          'location__category': row[13], 'location__subcategory': row[14],
          'location__available': row[15],
          'avgutil': round(row[16], 2),
          'available_calendar': row[17],
          'owner': row[18],
          'bucket': row[numfields - 6],
          'startdate': row[numfields - 5].date(),
          'available': round(row[numfields - 4], 1),
          'unavailable': round(row[numfields - 3], 1),
          'load': round(row[numfields - 2], 1),
          'setup': round(row[numfields - 1], 1),
          'utilization': round(util, 2)
          }
        idx = 17
        for f in getAttributeFields(Resource):
          result[f.field_name] = row[idx]
          idx += 1
        for f in getAttributeFields(Location):
          result[f.field_name] = row[idx]
          idx += 1
        yield result
