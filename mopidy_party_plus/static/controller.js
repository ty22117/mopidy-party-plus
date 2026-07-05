'use strict';

// VERSION MARKER v4: full back-history stack (fixes two-song ping-pong)
console.log("[PARTY_PLUS] Frontend version: 1.5.0-PARTY_PLUS_v4");

// TODO : add a mopidy service designed for angular, to avoid ugly $scope.$apply()...
angular.module('partyApp', [])
  .controller('MainController', function ($scope, $http) {

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
    $scope.queue = [];            // upcoming/current tracks in the tracklist
    $scope.showQueue = false;     // toggle for the queue panel
    $scope.history = [];          // stack of previously-played tracks, most recent last
    $scope.pendingBackNav = 0;    // how many "back" replays are in flight (skip history push for these)

    // Get the max tracks to lookup at once from the 'max_results' config value in mopidy.conf
    $http.get('/party_plus/config?key=max_results').then(function success (response) {
      if (response.status == 200) {
        $scope.maxTracksToLookup = response.data;
      }
    }, null);

    // Get the max song length 'max_song_duration' config value in mopidy.conf (minutes)
    $http.get('/party_plus/config?key=max_song_duration').then(function success (response) {
      if (response.status == 200) {
        $scope.maxSongLengthMS = response.data * 60000;
      }
    }, null);

    // Get the source priority list
    $http.get('/party_plus/config?key=source_prio').then(function success (response) {
      if (response.status == 200) {
        $scope.sources_priority = [...data.matchAll(/\w+/g)].map(x => x[0]);
      }
    }, null);
    // Get the source blacklist
    $http.get('/party_plus/config?key=source_blacklist').then(function success (response) {
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
          if (track)
            $scope.currentState.track = track;
          return mopidy.playback.getState();
        })
        .then(function (state) {
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
          $scope.$apply();
          $scope.search();
          $scope.refreshQueue();
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
      $scope.currentState.paused = (event.new_state === 'paused');
      $scope.$apply();
    });

    mopidy.on('event:trackPlaybackStarted', function (event) {
      var newUri = event.tl_track && event.tl_track.track ? event.tl_track.track.uri : null;
      var prev = $scope.currentState.track;
      if ($scope.pendingBackNav > 0) {
        // This playback was triggered by a "back" replay, not natural progression.
        // Don't push onto history, otherwise we'd just ping-pong between two songs.
        $scope.pendingBackNav--;
      } else if (prev && prev.uri && prev.uri !== newUri) {
        // A song finished (or was skipped) and the next one started: remember the
        // one that just played so we can back up through the full history.
        $scope.history.push(prev);
      }
      $scope.currentState.track = event.tl_track.track;
      $scope.currentState.position = 0;
      $scope.$apply();
      $scope.refreshQueue();
    });

    mopidy.on('event:tracklistChanged', function () {
      mopidy.tracklist.getLength().done(function (length) {
        $scope.currentState.length = length;
        $scope.$apply();
      });
      $scope.refreshQueue();
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

      $http.post('/party_plus/add', track.uri).then(
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

      $http.post('/party_plus/playlist', JSON.stringify(requestData), {
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
      if (!mopidy.tracklist) {
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
        $scope.refreshQueue();
      }
    };

    // "Last song": step back through the history of played tracks. Because consume
    // mode removes played tracks from the tracklist, we pop the most recent one off
    // the history stack, re-insert it at the current position, and play it.
    $scope.RESTART_THRESHOLD_MS = 3000; // within this many ms, "back" goes to the previous song
    $scope.playLastSong = function () {
      // Standard music-player behaviour: only jump to the previous song if we're
      // still in the first few seconds. Otherwise, restart the current song.
      if ($scope.currentState.position > $scope.RESTART_THRESHOLD_MS) {
        $scope.currentState.position = 0;
        $scope.seekTrack();
        $scope.message = ['success', 'Restarted current song'];
        return;
      }
      if (!$scope.history.length) {
        $scope.message = ['error', 'No previous song to replay yet'];
        return;
      }
      var prevTrack = $scope.history.pop();
      var uri = prevTrack.uri;
      var name = prevTrack.name;
      // Mark this playback as a "back" navigation so trackPlaybackStarted doesn't
      // record it as history (which is what caused the two-song ping-pong).
      $scope.pendingBackNav++;
      mopidy.tracklist.index().then(function (currentIndex) {
        var at = (currentIndex === null || currentIndex === undefined) ? 0 : currentIndex;
        return mopidy.tracklist.add({ uris: [uri], at_position: at });
      }).then(function (tlTracks) {
        if (tlTracks && tlTracks.length) {
          mopidy.playback.play({ tlid: tlTracks[0].tlid }).then(function () {
            $scope.$apply(function () {
              $scope.message = ['success', 'Replaying: ' + name];
            });
          });
        } else {
          // Add failed: undo the bookkeeping so we don't get stuck.
          $scope.pendingBackNav = Math.max(0, $scope.pendingBackNav - 1);
          $scope.history.push(prevTrack);
        }
      }, function (err) {
        $scope.pendingBackNav = Math.max(0, $scope.pendingBackNav - 1);
        $scope.history.push(prevTrack);
        $scope.$apply(function () {
          $scope.message = ['error', 'Unable to replay last song: ' + err];
        });
      });
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
      var _fn = $scope.currentState.paused ? mopidy.playback.resume : mopidy.playback.pause;
      _fn().done();
    };

    $scope.seekTrack = function () {
      // Prevent position updates while seek is in progress
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
              $scope.currentState.position = position;
            });
          }
        });
      }
    }, 200);
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
