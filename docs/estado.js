/* Estado de extracción separado de la fecha del último resultado deportivo. */
function evaluarEstado(estado, now=Date.now()) {
  if (!estado || !estado.comprobado) return {aviso:true,texto:'No se ha podido comprobar el estado de las actualizaciones.'};
  const fecha=Date.parse(estado.comprobado);
  const activo=!estado.actualizacion_hasta || now<=Date.parse(estado.actualizacion_hasta);
  if (!Number.isFinite(fecha) || (activo && now-fecha>15*60000))
    return {aviso:true,texto:'Las actualizaciones llevan más de 15 minutos sin completarse. Los resultados pueden estar desactualizados.'};
  if (estado.estado==='error') return {aviso:true,texto:'La última actualización ha fallado. Se conservan los resultados anteriores.'};
  if (estado.estado==='parcial') return {aviso:true,texto:'Actualización parcial: hay datos pendientes de verificar. El resto de partidos sigue actualizándose.'};
  return {aviso:false,texto:'Última comprobación correcta: '+new Date(fecha).toLocaleString('es-ES',{timeZone:'Europe/Madrid'})};
}
function renderEstado(estado, falloDatos=false) {
  const info=evaluarEstado(estado);
  const element=document.getElementById('health');
  element.textContent=falloDatos?'No se han podido descargar los datos del visor. Se mantiene la información anterior.':info.texto;
  element.className='meta'+(info.aviso||falloDatos?' warning':'');
  const details=document.getElementById('health-details');
  details.replaceChildren();
  for (const aviso of (estado?.incidencias||[])) {
    if(!aviso.jugador) continue;
    const item=document.createElement('div');
    item.textContent=aviso.jugador+' · '+aviso.rival+' — pendiente de verificar. ';
    if(aviso.url?.startsWith('https://pickleprotour.com/')) {
      const link=document.createElement('a');link.href=aviso.url;link.target='_blank';link.rel='noopener';link.textContent='Consultar fuente oficial';item.append(link);
    }
    details.append(item);
  }
}
function fechaLocalPartido(texto) {
  const m=(texto||'').match(/(\d{2})\/(\d{2})\/(\d{4})\s+(\d{1,2}):(\d{2})/);
  return m?Date.UTC(+m[3],+m[2]-1,+m[1],+m[4],+m[5]):null;
}
function estadoPendiente(m, now=Date.now()) {
  if(m.pendiente_verificacion) return 'Pendiente de verificar';
  const estado=m.estado_programacion||'Próximo';
  const cuando=fechaLocalPartido(m.horario_pista);
  const local=new Date(now).toLocaleString('sv-SE',{timeZone:'Europe/Madrid'});
  const momento=Date.parse(local.replace(' ','T')+'Z');
  if(cuando && momento-cuando>60*60000 && /^(Comienza|Próximo)/i.test(estado)) return 'Sin resultado publicado';
  return estado;
}
