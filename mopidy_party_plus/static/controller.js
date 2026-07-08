'use strict';

// VERSION MARKER: NETJammer — drawers, album art, playback-error toasts
console.log("[NETJammer] Frontend version: 1.6.1-NETJAMMER (stuck-head recovery)");

// TODO : add a mopidy service designed for angular, to avoid ugly $scope.$apply()...
angular.module('partyApp', [])
  .controller('MainController', function ($scope, $http, $timeout, $interval) {

    // Scope variables
    $scope.message = [];
    $scope.tracks = [];
    $scope.tracksToLookup = [];
    $scope.maxTracksToLookup = 50; // Will be overwritten later by module config
    $scope.loading = true;
    $scope.maxSongLengthMS = 0; //0 No limit. May be overwritten by module config
    $scope.searching = false;
    $scope.searchingSources = [];
    $scope.ready = false;
    $scope.playlistUrl = '';
    $scope.currentState = {
      paused: false,
      state: 'stopped',
      length: 0,
      position: 0,
      volume: 100,
      track: {
        length: 0,
        name: 'Nothing playing, add some songs to get the party going!'
      }
    };
    $scope.sources_blacklist = ['cd', 'file']; // Will be overwritten later by module config
    $scope.sources_priority = ['local'];       // Will be overwritten later by module config
    $scope.prioritized_sources = [];
    $scope.isSliderDragging = false;
    $scope.suppressSeek = false;  // true while we set the position programmatically, so the slider's ng-change doesn't issue a bogus seek
    $scope.queue = [];            // upcoming/current tracks in the tracklist
    $scope.showQueue = false;     // queue drawer open/closed
    $scope.showSearch = false;    // search drawer open/closed
    $scope.isSortingQueue = false; // true while dragging a queue item (pauses queue refresh so it isn't clobbered mid-drag)
    $scope.albumArt = null;       // image URL for the currently-playing track
    $scope.historyCount = 0;      // how many previously-played tracks the server has (for the back button)

    // Auto-dismiss status messages (shown as a toast) a few seconds after they appear.
    var messageTimer = null;
    $scope.$watch('message', function (msg) {
      if (messageTimer) {
        $timeout.cancel(messageTimer);
        messageTimer = null;
      }
      if (msg && msg.length) {
        messageTimer = $timeout(function () { $scope.message = []; }, 6000);
      }
    });

    // Poll the backend for playback/download errors (e.g. a YouTube video that
    // can't be downloaded) and surface them as a toast. The backend has no
    // websocket event for this, so it captures the relevant log lines instead.
    var lastErrorId = null; // null until the first poll establishes a baseline
    $scope.pollErrors = function () {
      var since = (lastErrorId === null) ? '' : lastErrorId;
      $http.get('/netjammer/errors', { params: { since: since } }).then(function (resp) {
        var d = resp.data || {};
        if (lastErrorId === null) {
          // First poll: remember where we are, don't replay pre-existing errors.
          lastErrorId = d.latest || 0;
          return;
        }
        lastErrorId = d.latest || lastErrorId;
        var errs = d.errors || [];
        if (errs.length) {
          showPlaybackError(errs[errs.length - 1]); // most recent
        }
      }, function () { /* ignore transient poll failures */ });
    };
    $interval($scope.pollErrors, 3000);

    function showPlaybackError(e) {
      var reason = e.reason || 'A track could not be played.';
      if (e.uri && $scope.ready && mopidy.library) {
        // Resolve the track name so the toast is friendly.
        mopidy.library.lookup({ uris: [e.uri] }).then(function (res) {
          var arr = res && res[e.uri];
          var name = (arr && arr.length && arr[0]) ? arr[0].name : null;
          $scope.$apply(function () {
            $scope.message = ['error', name
              ? ('Couldn’t play “' + name + '” — ' + reason)
              : reason];
          });
        }, function () {
          $scope.$apply(function () { $scope.message = ['error', reason]; });
        });
      } else {
        $scope.message = ['error', reason];
      }
    }

    // Playback watchdog: recover from a "stuck" queue. If a track fails to play
    // (e.g. a YouTube video that 403s), Mopidy briefly starts it (cover art shows)
    // then drops to "stopped" and does NOT auto-advance, leaving songs queued but
    // nothing playing. This app only auto-starts on an add, so it can stay stuck.
    //
    // We always act on the HEAD of the tracklist (index 0): under consume mode the
    // head is the next-to-play, so it's the culprit when we're stuck. We also play
    // an explicit tlid rather than a bare play(), which can target a stale/removed
    // "current" track and silently do nothing (that was the never-recovers bug).
    var stuckCount = 0;
    function playbackWatchdog() {
      if (!$scope.ready || $scope.isSortingQueue) {
        return;
      }
      mopidy.playback.getState().then(function (state) {
        if (state !== 'stopped') {
          stuckCount = 0;
          return;
        }
        mopidy.tracklist.getTlTracks().then(function (tls) {
          if (!tls || !tls.length) {
            stuckCount = 0; // stopped with an empty queue is normal
            return;
          }
          stuckCount++;
          if (stuckCount === 1) {
            // Gentle nudge: explicitly (re)start the head track.
            mopidy.playback.play({ tlid: tls[0].tlid });
          } else {
            // Still stopped after a nudge: the head track is unplayable. Drop it
            // and start the next one, so one bad song can't freeze the party.
            mopidy.tracklist.remove([{ tlid: [tls[0].tlid] }]).then(function () {
              mopidy.tracklist.getTlTracks().then(function (rest) {
                if (rest && rest.length) {
                  mopidy.playback.play({ tlid: rest[0].tlid });
                }
              });
              $scope.$apply(function () {
                $scope.message = ['error', 'Skipped a track that wouldn’t play, keeping the music going.'];
              });
              $scope.refreshQueue();
            });
            stuckCount = 0; // give the new head its own nudge next cycle before removing
          }
        });
      });
    }
    $interval(playbackWatchdog, 4000);

    // Get the max tracks to lookup at once from the 'max_results' config value in mopidy.conf
    $http.get('/netjammer/config?key=max_results').then(function success (response) {
      if (response.status == 200) {
        $scope.maxTracksToLookup = response.data;
      }
    }, null);

    // Get the max song length 'max_song_duration' config value in mopidy.conf (minutes)
    $http.get('/netjammer/config?key=max_song_duration').then(function success (response) {
      if (response.status == 200) {
        $scope.maxSongLengthMS = response.data * 60000;
      }
    }, null);

    // Get the source priority list
    $http.get('/netjammer/config?key=source_prio').then(function success (response) {
      if (response.status == 200) {
        $scope.sources_priority = [...data.matchAll(/\w+/g)].map(x => x[0]);
      }
    }, null);
    // Get the source blacklist
    $http.get('/netjammer/config?key=source_blacklist').then(function success (response) {
      if (response.status == 200) {
        $scope.sources_blacklist = [...data.matchAll(/\w+/g)].map(x => x[0]);
      }
    }, null);

    var mopidy = new Mopidy({
      'callingConvention': 'by-position-or-by-name'
    });

    mopidy.on('state:online', function () {
      mopidy.playback
        .getCurrentTrack()
        .then(function (track) {
          if (track) {
            $scope.currentState.track = track;
            $scope.fetchAlbumArt(track);
          }
          return mopidy.playback.getState();
        })
        .then(function (state) {
          $scope.currentState.state = state;
          $scope.currentState.paused = (state === 'paused');
          return mopidy.tracklist.getLength();
        })
        .then(function (length) {
          $scope.currentState.length = length;
          return mopidy.playback.getTimePosition();
        })
        .then(function (position) {
          if (position !== undefined && position !== null) {
            $scope.currentState.position = position;
          }
          return mopidy.mixer.getVolume();
        })
        .then(function (volume) {
          if (volume !== undefined && volume !== null) {
            $scope.currentState.volume = volume;
          }
        })
        .done(function () {
          $scope.ready = true;
          $scope.loading = false;
          $scope.searching = false;
          // The first digest renders the slider at the real position while its max
          // is briefly still 100ms; suppress the resulting clamp/ng-change so we
          // don't seek (which restarted the song on load).
          $scope.suppressSeek = true;
          $scope.$apply();
          setTimeout(function () {
            $scope.suppressSeek = false;
          }, 0);
          $scope.search();
          $scope.refreshQueue();
          $scope.refreshHistory();
        });

      /* Initialize available sources */
      mopidy.library.browse({ "uri": null }).done(
        function (uri_results){
          $scope.sources = uri_results.map(source => source.uri.split(":")[0]);
          $scope.prioritized_sources = getPrioritizedSources($scope.sources, $scope.sources_priority, $scope.sources_blacklist)
        }
      );

    });

    mopidy.on('event:playbackStateChanged', function (event) {
      $scope.currentState.state = event.new_state;
      $scope.currentState.paused = (event.new_state === 'paused');
      $scope.$apply();
    });

    // Keep the volume in sync across everyone's screens. Mopidy broadcasts this
    // whenever anyone (any connected client) changes the volume, so we just apply
    // it. Setting the value programmatically doesn't re-trigger setVolume (the
    // value is always within range, so the slider fires no ng-change), so there's
    // no feedback loop.
    mopidy.on('event:volumeChanged', function (event) {
      if (event && event.volume !== undefined && event.volume !== null) {
        $scope.currentState.volume = event.volume;
        $scope.$apply();
      }
    });

    mopidy.on('event:trackPlaybackStarted', function (event) {
      $scope.currentState.track = event.tl_track.track;
      $scope.currentState.position = 0;
      $scope.$apply();
      $scope.fetchAlbumArt(event.tl_track.track);
      $scope.refreshQueue();
      $scope.refreshHistory();
    });

    mopidy.on('event:trackPlaybackEnded', function () {
      // History is recorded server-side now (shared + survives refresh); just
      // refresh our count so the back button state is current.
      $scope.refreshHistory();
    });

    mopidy.on('event:tracklistChanged', function () {
      mopidy.tracklist.getLength().done(function (length) {
        $scope.currentState.length = length;
        if (length === 0) {
          // Nothing queued or playing -- clear the "now playing" display so we
          // don't show stale album art with dead controls.
          $scope.currentState.track = {
            length: 0,
            name: 'Nothing playing, add some songs to get the party going!'
          };
          $scope.currentState.position = 0;
          $scope.albumArt = null;
        }
        $scope.$apply();
      });
      $scope.refreshQueue();
      $scope.refreshHistory();
    });

    $scope.printDuration = function (track) {
      if (!track.length)
        return '';

      var _sum = parseInt(track.length / 1000);
      var _min = parseInt(_sum / 60);
      var _sec = _sum % 60;

      return '(' + _min + ':' + (_sec < 10 ? '0' + _sec : _sec) + ')';
    };

    $scope.printTime = function (ms) {
      if (!ms)
        return '0:00';

      var _sum = parseInt(ms / 1000);
      var _min = parseInt(_sum / 60);
      var _sec = _sum % 60;

      return _min + ':' + (_sec < 10 ? '0' + _sec : _sec);
    };

    $scope.search = function () {
      $scope.message = [];
      $scope.tracks = [];
      $scope.tracksToLookup = [];
      $scope.searchingSources = [];

      if (!$scope.searchField) {
        $scope.browse();
      } else {
        $scope.searchSourcesInOrder();
      }
    };

    $scope.browse = function () {
        mopidy.library.browse({
          'uri': 'local:directory'  //TODO: depend on source_prio
        }).done($scope.handleBrowseResult);
        return;
    }

    $scope.handleBrowseResult = function (res) {
      $scope.loading = false;
      $scope.searching = false;
      $scope.tracks = [];
      $scope.tracksToLookup = [];

      for (var i = 0; i < res.length; i++) {
        if (res[i].type == 'directory' && res[i].uri == 'local:directory?type=track') {
          mopidy.library.browse({
            'uri': res[i].uri
          }).done($scope.handleBrowseResult);
        } else if (res[i].type == 'track') {
          $scope.tracksToLookup.push(res[i].uri);
        }
      }

      if ($scope.tracksToLookup) {
        $scope.lookupOnePageOfTracks();
      }
    }

    $scope.lookupOnePageOfTracks = function () {
      mopidy.library.lookup({ 'uris': $scope.tracksToLookup.splice(0, $scope.maxTracksToLookup) }).done(function (tracklistResult) {
        Object.values(tracklistResult).map(function (singleTrackResult) { return singleTrackResult[0]; }).forEach($scope.addTrackResult);
      });
    };

    $scope.searchSourcesInOrder = function () {
      $scope.searchingSources = angular.copy($scope.prioritized_sources);
      $scope.searching = true;

      for (const src of $scope.prioritized_sources) {
        $scope.searchSources([src]);
      }
    }

    $scope.searchSources = function ($sourceList) {
      if($sourceList.length > 0) {
        mopidy.library.search({
          'query': {
            'any': [$scope.searchField]
          },
          'uris': $sourceList.map(source => source + ':')
        }).done($scope.handleSearchResult);
      }
    }

    $scope.handleSearchResult = function (res) {
      var _index = 0;
      var _found = true;
      const index = $scope.searchingSources.indexOf(getSource(res));
      if (index !== -1) {
        $scope.searchingSources.splice(index, 1);
      }
      for (var i = 0; i < res.length; i++) {
        if (res[i].tracks) {
          for (var j = 0; j < res[i].tracks.length; j++) {
            if (res[i].tracks[j]) {
              if ($scope.maxSongLengthMS <= 0 || res[i].tracks[j].length <= $scope.maxSongLengthMS) {
                $scope.addTrackResult(res[i].tracks[j]);
                _index++;
                if (_index >= $scope.maxTracksToLookup) {
                  break;
                }
              }
            }
          }
        }
        if (_index >= $scope.maxTracksToLookup) {
          break;
        }
      }
      if ($scope.searchingSources.length < 1) {
        $scope.searching = false;
      }
      $scope.$apply();
    };

    $scope.addTrackResult = function (track) {
      $scope.tracks.push(track);
      mopidy.tracklist.filter([{ 'uri': [track.uri] }]).done(
        function (matches) {
          if (matches.length) {
            for (var i = 0; i < $scope.tracks.length; i++) {
              if ($scope.tracks[i].uri == matches[0].track.uri)
                $scope.tracks[i].disabled = true;
            }
          }
          $scope.$apply();
        });
    };

    $scope.addTrack = function (track) {
      track.disabled = true;

      $http.post('/netjammer/add', track.uri).then(
        function success(response) {
          $scope.message = ['success', 'Queued: ' + track.name];
        },
        function error(response) {
          if (response.status === 409) {
            $scope.message = ['error', '' + response.data];
          } else {
            $scope.message = ['error', 'Code ' + response.status + ' - ' + response.data];
          }
        }
      );
    };

    $scope.addPlaylist = function () {
      if (!$scope.playlistUrl) {
        $scope.message = ['error', 'Please enter a playlist or album URL'];
        return;
      }

      var requestData = {
        url: $scope.playlistUrl,
        source: 'auto'
      };

      $http.post('/netjammer/playlist', JSON.stringify(requestData), {
        headers: {'Content-Type': 'application/json'}
      }).then(
        function success(response) {
          if (response.data && response.data.success) {
            $scope.message = ['success', response.data.message];
            $scope.playlistUrl = ''; // Clear input
          } else if (response.data && response.data.error) {
            $scope.message = ['error', response.data.error];
          } else {
            $scope.message = ['success', 'Playlist added successfully!'];
            $scope.playlistUrl = '';
          }
        },
        function error(response) {
          try {
            var errorMsg = response.data && response.data.error ? response.data.error : response.data;
            $scope.message = ['error', 'Error: ' + errorMsg];
          } catch (e) {
            $scope.message = ['error', 'Code ' + response.status + ' - Failed to add playlist'];
          }
        }
      );
    };

    $scope.nextTrack = function () {
      // Instant host skip: advance the tracklist immediately (no voting).
      mopidy.playback.next().then(function () {
        $scope.$apply(function () {
          $scope.message = ['success', 'Skipped to next track'];
        });
      }, function (err) {
        $scope.$apply(function () {
          $scope.message = ['error', 'Unable to skip: ' + err];
        });
      });
    };

    // Fetch the current tracklist (current + upcoming songs). With consume mode
    // enabled, played tracks are removed, so the tracklist is effectively the queue.
    $scope.refreshQueue = function () {
      if (!mopidy.tracklist || $scope.isSortingQueue) {
        // Don't rebuild the list from the server while the user is dragging an item.
        return;
      }
      mopidy.tracklist.getTlTracks().then(function (tlTracks) {
        mopidy.tracklist.index().then(function (currentIndex) {
          var idx = (currentIndex === null || currentIndex === undefined) ? -1 : currentIndex;
          // Only show upcoming songs. The currently-playing song (and anything the
          // consume mode has already removed) is not part of the queue. When you
          // back up, the previous song is re-inserted ahead of it, so it reappears.
          $scope.$apply(function () {
            $scope.queue = (tlTracks || [])
              .map(function (tl, i) {
                return { track: tl.track, tlid: tl.tlid, position: i };
              })
              .filter(function (item) {
                return item.position > idx;
              });
          });
        });
      });
    };

    $scope.toggleQueue = function () {
      $scope.showQueue = !$scope.showQueue;
      if ($scope.showQueue) {
        $scope.showSearch = false; // only one drawer open at a time
        $scope.refreshQueue();
      }
    };

    $scope.toggleSearch = function () {
      $scope.showSearch = !$scope.showSearch;
      if ($scope.showSearch) {
        $scope.showQueue = false; // only one drawer open at a time
      }
    };

    $scope.closeDrawers = function () {
      $scope.showQueue = false;
      $scope.showSearch = false;
    };

    // Look up album art for a track via Mopidy's library.getImages and pick the
    // largest available image. Falls back to no art (the UI shows a placeholder).
    $scope.fetchAlbumArt = function (track) {
      $scope.albumArt = null;
      if (!track || !track.uri) {
        return;
      }
      var uri = track.uri;
      mopidy.library.getImages({ uris: [uri] }).then(function (result) {
        var images = result && result[uri];
        var best = null;
        if (images && images.length) {
          best = images[0];
          for (var i = 1; i < images.length; i++) {
            var a = (images[i].width || 0) * (images[i].height || 0);
            var b = (best.width || 0) * (best.height || 0);
            if (a > b) {
              best = images[i];
            }
          }
        }
        $scope.$apply(function () {
          $scope.albumArt = best ? best.uri : null;
        });
      });
    };

    // Remove a single upcoming track from the queue.
    $scope.removeFromQueue = function (item) {
      if (!item || item.tlid === undefined || item.tlid === null) {
        return;
      }
      mopidy.tracklist.remove([{ tlid: [item.tlid] }]).then(function () {
        $scope.refreshQueue();
      });
    };

    // Clear the whole queue (all upcoming tracks). The currently-playing song is
    // not part of the queue, so it keeps playing.
    $scope.clearQueue = function () {
      var tlids = $scope.queue.map(function (item) { return item.tlid; });
      if (!tlids.length) {
        return;
      }
      mopidy.tracklist.remove([{ tlid: tlids }]).then(function () {
        $scope.message = ['success', 'Cleared the queue'];
        $scope.$apply();
        $scope.refreshQueue();
      });
    };

    // Move an upcoming track one slot earlier/later. Mopidy's move takes a slice
    // [start, end) and a destination index; moving a single track at position p up
    // means slice [p, p+1) -> p-1, and down means -> p+1.
    $scope.moveUp = function (item) {
      var p = item.position;
      mopidy.tracklist.move([p, p + 1, p - 1]).then(function () {
        $scope.refreshQueue();
      });
    };

    $scope.moveDown = function (item) {
      var p = item.position;
      mopidy.tracklist.move([p, p + 1, p + 1]).then(function () {
        $scope.refreshQueue();
      });
    };

    // Called by the drag-and-drop directive when a queue item is dropped. The
    // directive has already reordered $scope.queue live, so queue[to] is the
    // dragged item and its .position still holds its original tracklist index.
    // Commit the reorder to Mopidy with a single tracklist.move.
    $scope.onQueueSorted = function (from, to) {
      if (from === to) {
        $scope.refreshQueue();
        return;
      }
      var item = $scope.queue[to];
      if (!item) {
        $scope.refreshQueue();
        return;
      }
      var origTlPos = item.position;         // dragged item's tracklist index before the move
      var newTlPos = origTlPos - from + to;  // queue block is contiguous, so shift by the same delta
      mopidy.tracklist.move([origTlPos, origTlPos + 1, newTlPos]).then(function () {
        $scope.refreshQueue();
      });
    };

    // Fetch how many previously-played tracks the server is holding, so the back
    // button knows whether there's anything to go back to. Server-side history is
    // shared and survives page refreshes / new clients joining.
    $scope.refreshHistory = function () {
      $http.get('/netjammer/history').then(function (resp) {
        $scope.historyCount = (resp.data && resp.data.count) || 0;
      }, function () { /* ignore */ });
    };

    // "Last song": if we're past the first few seconds of the current song, restart
    // it; otherwise ask the server to replay the previous track (shared history).
    $scope.RESTART_THRESHOLD_MS = 3000;
    $scope.playLastSong = function () {
      if ($scope.currentState.length > 0 && $scope.currentState.position > $scope.RESTART_THRESHOLD_MS) {
        $scope.currentState.position = 0;
        $scope.seekTrack();
        $scope.message = ['success', 'Restarted current song'];
        return;
      }
      $http.post('/netjammer/previous', '').then(
        function (resp) {
          if (resp.data && resp.data.name) {
            $scope.message = ['success', 'Replaying: ' + resp.data.name];
          }
          $scope.refreshHistory();
        },
        function (resp) {
          var msg = (resp.data && resp.data.error) ? resp.data.error : 'No previous song to play yet';
          $scope.message = ['error', msg];
          $scope.refreshHistory();
        }
      );
    };

    $scope.getTrackSource = function (track) {
      var sourceAsText = 'unknown';
      if (track.uri) {
        sourceAsText = track.uri.split(':', '1')[0];
      }

      return sourceAsText;
    };

    $scope.getFontAwesomeIcon = function (source) {
      var sources_with_fa_icon = ['bandcamp', 'mixcloud', 'pandora', 'soundcloud', 'spotify', 'youtube', 'tidal'];
      var css_class = 'fa fa-music';

      if (source == 'local') {
        css_class = 'fa fa-folder';
      } else if (sources_with_fa_icon.includes(source)) {
        css_class = 'fa-brands fa-' + source;
      }

      return css_class;
    };

    $scope.togglePause = function () {
      // Handle all three states: playing -> pause, paused -> resume, stopped -> play.
      // (Previously "stopped" fell through to pause() and did nothing, so a queued
      // song that had stopped couldn't be started from the button.)
      if ($scope.currentState.state === 'playing') {
        mopidy.playback.pause().done();
      } else if ($scope.currentState.state === 'paused') {
        mopidy.playback.resume().done();
      } else {
        mopidy.playback.play().done();
      }
    };

    $scope.seekTrack = function () {
      // The range slider's ng-change also fires when WE update currentState.position
      // (initial load and the 200ms poll). On load the slider's max is briefly 100ms
      // until the track length is known, so AngularJS clamps the value and fires a
      // change that seeked to ~0 -- restarting the song on every page load. Ignore
      // those programmatic changes; only real user drags should seek.
      if ($scope.suppressSeek) {
        return;
      }
      // Prevent position updates (the poll) from fighting the seek while it's in flight.
      $scope.isSliderDragging = true;
      // Mopidy's seek RPC takes a "time_position" argument (in ms), NOT "value".
      // Using the wrong name made every seek a silent no-op, so the slider could
      // display the position but never actually move playback.
      mopidy.playback.seek({time_position: Math.floor($scope.currentState.position)}).done(function() {
        // Re-enable position updates after seek completes
        setTimeout(function() {
          $scope.isSliderDragging = false;
        }, 300);
      });
    };

    // Update currentState.position without letting the slider's ng-change treat it
    // as a user seek. Clears the flag on the next tick, after the digest (and any
    // resulting clamp/ng-change) has run.
    function setPositionSilently(position) {
      $scope.suppressSeek = true;
      $scope.currentState.position = position;
      setTimeout(function () {
        $scope.suppressSeek = false;
      }, 0);
    }

    $scope.setVolume = function () {
      mopidy.mixer.setVolume({volume: Math.floor($scope.currentState.volume)}).done();
    };

    $scope.onSliderDown = function () {
      $scope.isSliderDragging = true;
    };

    $scope.onSliderUp = function () {
      // Don't re-enable polling immediately — the seek triggered by ng-change is
      // async, and the poll could otherwise snap the slider back to the old
      // position before the seek lands. seekTrack()'s timeout re-enables it.
      setTimeout(function () {
        $scope.isSliderDragging = false;
      }, 300);
    };

    // Update playback position every 200ms
    var positionUpdateInterval = setInterval(function () {
      if ($scope.ready && !$scope.currentState.paused && !$scope.isSliderDragging) {
        mopidy.playback.getTimePosition().done(function (position) {
          if (position !== undefined && position !== null) {
            $scope.$apply(function () {
              setPositionSilently(position);
            });
          }
        });
      }
    }, 200);
  })
  // Drag-and-drop reordering for the queue. Uses Pointer Events so it works with
  // both a mouse and touch (phones). Dragging starts from an element with class
  // "drag-handle"; each reorderable row is marked with the "data-sortable-item"
  // attribute. As the pointer moves, the bound array (dnd-sortable) is reordered
  // live so the rows shift under the finger; on release, dnd-on-sort is evaluated
  // with $from / $to (the start and end indices) to commit the change.
  .directive('dndSortable', function () {
    return {
      restrict: 'A',
      link: function (scope, element, attrs) {
        var listEl = element[0];
        var startIndex = null;   // row index where the drag began
        var currentIndex = null; // row index the dragged item currently occupies
        var activePointer = null;

        function itemRows() {
          return Array.prototype.slice.call(
            listEl.querySelectorAll('[data-sortable-item]')
          );
        }

        function onDown(e) {
          var handle = e.target.closest ? e.target.closest('.drag-handle') : null;
          if (!handle) {
            return;
          }
          var row = handle.closest('[data-sortable-item]');
          if (!row) {
            return;
          }
          startIndex = itemRows().indexOf(row);
          if (startIndex < 0) {
            startIndex = null;
            return;
          }
          currentIndex = startIndex;
          activePointer = e.pointerId;
          e.preventDefault();
          try { listEl.setPointerCapture(activePointer); } catch (err) { /* ignore */ }
          row.classList.add('dnd-dragging');
          scope.$apply(function () { scope.isSortingQueue = true; });
        }

        function onMove(e) {
          if (startIndex === null) {
            return;
          }
          e.preventDefault();
          var rows = itemRows();
          var y = e.clientY;
          var target = rows.length - 1;
          for (var i = 0; i < rows.length; i++) {
            var r = rows[i].getBoundingClientRect();
            if (y < r.top + r.height / 2) { target = i; break; }
          }
          if (target !== currentIndex && target >= 0) {
            scope.$apply(function () {
              var arr = scope.$eval(attrs.dndSortable);
              var moved = arr.splice(currentIndex, 1)[0];
              arr.splice(target, 0, moved);
            });
            currentIndex = target;
          }
        }

        function onUp() {
          if (startIndex === null) {
            return;
          }
          try { listEl.releasePointerCapture(activePointer); } catch (err) { /* ignore */ }
          itemRows().forEach(function (r) { r.classList.remove('dnd-dragging'); });
          var from = startIndex, to = currentIndex;
          startIndex = null;
          currentIndex = null;
          activePointer = null;
          scope.$apply(function () {
            scope.isSortingQueue = false;
            scope.$eval(attrs.dndOnSort, { $from: from, $to: to });
          });
        }

        listEl.addEventListener('pointerdown', onDown);
        listEl.addEventListener('pointermove', onMove);
        listEl.addEventListener('pointerup', onUp);
        listEl.addEventListener('pointercancel', onUp);
      }
    };
  });

function getPrioritizedSources (availablesources, sourceprio, blacklist) {
    const blacklistSet = new Set(blacklist); //eliminate duplicates
    const availableSet = new Set(availablesources);
    const prioritized = sourceprio.filter(src => availableSet.has(src) && !blacklistSet.has(src));
    const remaining = availablesources.filter(src => !blacklistSet.has(src) && !prioritized.includes(src));
    return [...prioritized, ...remaining];
}

function findFirstUri (obj) {
  if (typeof obj !== 'object' || obj === null) return null;

  if ('uri' in obj && typeof obj.uri === 'string') {
    return obj.uri;
  }

  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      const found = findFirstUri(obj[key]);
      if (found) return found;
    }
  }

  return null;
}

function getSource (result) {
  var uri = findFirstUri(result);
  if (uri) {
    return uri.split(':', '1')[0];
  }
  return ""
}
